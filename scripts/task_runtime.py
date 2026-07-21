#!/usr/bin/env python3
"""Local, inactive SQLite Task Runtime proof for Hermes workflows.

This module deliberately has no network, tool, model, cron, or messaging integration.
It provides a durable task/event store and a synthetic dry-run path so the execution
contract can be tested before any live adapter is introduced.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any


class TaskRuntimeError(RuntimeError):
    """Raised when an operation would violate the durable task contract."""


TRANSITIONS: dict[str, set[str]] = {
    "received": {"briefing", "failed", "cancelled"},
    "briefing": {"ready_to_build", "failed", "cancelled"},
    "ready_to_build": {"building", "awaiting_approval", "failed", "cancelled"},
    "building": {"verifying", "awaiting_approval", "failed", "cancelled"},
    "verifying": {"awaiting_approval", "completed", "failed", "cancelled"},
    "awaiting_approval": {"shipping", "failed", "cancelled"},
    "shipping": {"maintaining", "completed", "failed", "cancelled"},
    "maintaining": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}
TERMINAL_STATES = {"completed", "failed", "cancelled"}
LEGACY_STATE_MAP = {
    "in_progress": "building",
    "blocked": "awaiting_approval",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TaskRuntime:
    """Small SQLite authority for a single agent/profile's durable task records."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                state TEXT NOT NULL,
                parent_task_id TEXT REFERENCES tasks(task_id),
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(agent_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                event_type TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_task_id_event_id ON events(task_id, event_id);
            """
        )
        self.connection.commit()

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        return item

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["detail"] = json.loads(item.pop("detail_json"))
        return item

    def _append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO events(task_id, event_type, from_state, to_state, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, event_type, from_state, to_state, json.dumps(detail or {}, sort_keys=True), now_iso()),
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskRuntimeError(f"unknown task: {task_id}")
        return self._task_from_row(row)

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        self.get_task(task_id)
        rows = self.connection.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY event_id", (task_id,)
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def create_or_get_task(
        self,
        agent_id: str,
        idempotency_key: str,
        title: str,
        *,
        parent_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if not agent_id or not idempotency_key or not title:
            raise TaskRuntimeError("agent_id, idempotency_key, and title are required")
        if parent_task_id is not None:
            self.get_task(parent_task_id)
        task_id = task_id or str(uuid.uuid4())
        timestamp = now_iso()
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO tasks(task_id, agent_id, title, idempotency_key, state, parent_task_id,
                                         metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'received', ?, ?, ?, ?)""",
                    (
                        task_id,
                        agent_id,
                        title,
                        idempotency_key,
                        parent_task_id,
                        json.dumps(metadata or {}, sort_keys=True),
                        timestamp,
                        timestamp,
                    ),
                )
                self._append_event(task_id, "task.created", to_state="received", detail={"idempotency_key": idempotency_key})
            return {"task": self.get_task(task_id), "created": True}
        except sqlite3.IntegrityError:
            row = self.connection.execute(
                "SELECT * FROM tasks WHERE agent_id = ? AND idempotency_key = ?", (agent_id, idempotency_key)
            ).fetchone()
            if row is None:
                raise
            return {"task": self._task_from_row(row), "created": False}

    def transition(self, task_id: str, to_state: str, reason: str) -> dict[str, Any]:
        if to_state not in TRANSITIONS:
            raise TaskRuntimeError(f"unknown target state: {to_state}")
        task = self.get_task(task_id)
        from_state = task["state"]
        if to_state not in TRANSITIONS[from_state]:
            raise TaskRuntimeError(f"invalid transition: {from_state} -> {to_state}")
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?", (to_state, now_iso(), task_id)
            )
            self._append_event(
                task_id,
                "task.transitioned",
                from_state=from_state,
                to_state=to_state,
                detail={"reason": reason},
            )
        return self.get_task(task_id)

    def await_approval(self, task_id: str, requested_action: str) -> dict[str, Any]:
        if not requested_action:
            raise TaskRuntimeError("requested_action is required")
        task = self.get_task(task_id)
        from_state = task["state"]
        if "awaiting_approval" not in TRANSITIONS[from_state]:
            raise TaskRuntimeError(f"invalid transition: {from_state} -> awaiting_approval")
        updated_metadata = dict(task["metadata"])
        updated_metadata["approval_request"] = requested_action
        updated_metadata["approval_status"] = "pending"
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET metadata_json = ?, state = 'awaiting_approval', updated_at = ? WHERE task_id = ?",
                (json.dumps(updated_metadata, sort_keys=True), now_iso(), task_id),
            )
            self._append_event(
                task_id,
                "task.transitioned",
                from_state=from_state,
                to_state="awaiting_approval",
                detail={"reason": f"approval required: {requested_action}"},
            )
        return self.get_task(task_id)

    def approve(self, task_id: str, approver: str) -> dict[str, Any]:
        if not approver:
            raise TaskRuntimeError("approver is required")
        task = self.get_task(task_id)
        if task["state"] != "awaiting_approval":
            raise TaskRuntimeError("task is not awaiting approval")
        metadata = dict(task["metadata"])
        metadata["approval_status"] = "approved"
        metadata["approved_by"] = approver
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET metadata_json = ?, updated_at = ? WHERE task_id = ?",
                (json.dumps(metadata, sort_keys=True), now_iso(), task_id),
            )
            self._append_event(task_id, "task.approved", detail={"approver": approver})
        return self.transition(task_id, "shipping", "approval received")

    def attempt_action(self, task_id: str, action: str, *, consequential: bool) -> dict[str, Any]:
        task = self.get_task(task_id)
        if consequential and task["state"] == "awaiting_approval":
            result = {"status": "blocked", "reason": "awaiting_approval", "action": action}
            with self.connection:
                self._append_event(task_id, "action.blocked", detail=result)
            return result
        if consequential and task["state"] != "shipping":
            result = {"status": "blocked", "reason": "state_not_authorized", "action": action}
            with self.connection:
                self._append_event(task_id, "action.blocked", detail=result)
            return result
        result = {"status": "allowed", "action": action, "consequential": consequential}
        with self.connection:
            self._append_event(task_id, "action.allowed", detail=result)
        return result

    def create_child_task(
        self, parent_task_id: str, agent_id: str, idempotency_key: str, title: str
    ) -> dict[str, Any]:
        return self.create_or_get_task(
            agent_id,
            idempotency_key,
            title,
            parent_task_id=parent_task_id,
            metadata={"delegated": True},
        )["task"]

    def import_json_ledger(self, source: str | Path, *, agent_id: str) -> dict[str, int]:
        """Read legacy JSON-ledger records without changing the source file."""
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            raise TaskRuntimeError("legacy ledger tasks must be an object")
        imported = skipped = 0
        for key, legacy in tasks.items():
            if not isinstance(legacy, dict):
                skipped += 1
                continue
            legacy_id = str(legacy.get("task_id") or key)
            existing = self.connection.execute("SELECT task_id FROM tasks WHERE task_id = ?", (legacy_id,)).fetchone()
            if existing is not None:
                skipped += 1
                continue
            legacy_status = str(legacy.get("status") or "in_progress")
            state = LEGACY_STATE_MAP.get(legacy_status, "received")
            timestamp = now_iso()
            metadata = {"legacy_import": True, "legacy_status": legacy_status, "legacy_origin": legacy.get("origin")}
            with self.connection:
                self.connection.execute(
                    """INSERT INTO tasks(task_id, agent_id, title, idempotency_key, state, parent_task_id,
                                         metadata_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                    (
                        legacy_id,
                        agent_id,
                        str(legacy.get("title") or legacy_id),
                        f"legacy:{legacy_id}",
                        state,
                        json.dumps(metadata, sort_keys=True),
                        timestamp,
                        timestamp,
                    ),
                )
                self._append_event(
                    legacy_id,
                    "task.imported_legacy",
                    to_state=state,
                    detail={"legacy_task_id": legacy_id, "legacy_status": legacy_status},
                )
            imported += 1
        return {"imported": imported, "skipped": skipped}

    def run_dry_run(self, agent_id: str) -> dict[str, Any]:
        """Run a fully synthetic lifecycle. No external action is dispatched."""
        created = self.create_or_get_task(agent_id, "dry-run:synthetic:1", "Synthetic Task Runtime proof")
        task = created["task"]
        duplicate = self.create_or_get_task(agent_id, "dry-run:synthetic:1", "Duplicate synthetic trigger")
        for state, reason in (
            ("briefing", "synthetic brief"),
            ("ready_to_build", "synthetic approval to build"),
            ("building", "synthetic build"),
            ("verifying", "synthetic verification"),
        ):
            self.transition(task["task_id"], state, reason)
        self.await_approval(task["task_id"], "synthetic consequential action")
        blocked = self.attempt_action(task["task_id"], "synthetic_send", consequential=True)
        self.approve(task["task_id"], "synthetic-approver")
        allowed = self.attempt_action(task["task_id"], "synthetic_send", consequential=True)
        self.transition(task["task_id"], "maintaining", "synthetic maintenance")
        final = self.transition(task["task_id"], "completed", "synthetic completion")
        return {
            "mode": "dry-run",
            "task_id": task["task_id"],
            "duplicate_task_id": duplicate["task"]["task_id"],
            "duplicate_suppressed": not duplicate["created"],
            "blocked_action": blocked,
            "allowed_action": allowed,
            "final_state": final["state"],
            "event_count": len(self.list_events(task["task_id"])),
            "external_side_effects": [],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run", help="run a synthetic zero-side-effect lifecycle")
    dry_run.add_argument("--agent", required=True)
    importer = subparsers.add_parser("import-ledger", help="import a local JSON ledger without modifying it")
    importer.add_argument("--db", required=True)
    importer.add_argument("--ledger", required=True)
    importer.add_argument("--agent", required=True)
    args = parser.parse_args()

    if args.command == "dry-run":
        with tempfile.TemporaryDirectory(prefix="task-runtime-dry-run-") as directory:
            runtime = TaskRuntime(Path(directory) / "runtime.sqlite3")
            try:
                print(json.dumps(runtime.run_dry_run(args.agent), sort_keys=True))
            finally:
                runtime.close()
        return 0

    runtime = TaskRuntime(args.db)
    try:
        print(json.dumps(runtime.import_json_ledger(args.ledger, agent_id=args.agent), sort_keys=True))
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
