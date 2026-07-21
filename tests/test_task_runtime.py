#!/usr/bin/env python3
"""Deterministic tests for the local inactive Task Runtime proof."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "task_runtime.py"
spec = importlib.util.spec_from_file_location("task_runtime", MODULE_PATH)
assert spec and spec.loader
runtime_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime_module
spec.loader.exec_module(runtime_module)

TaskRuntime = runtime_module.TaskRuntime
TaskRuntimeError = runtime_module.TaskRuntimeError


class TaskRuntimeTests(unittest.TestCase):
    def make_runtime(self) -> tuple[tempfile.TemporaryDirectory[str], TaskRuntime]:
        tmp = tempfile.TemporaryDirectory()
        return tmp, TaskRuntime(Path(tmp.name) / "runtime.sqlite3")

    def test_first_trigger_creates_durable_task_and_event(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        result = runtime.create_or_get_task(
            agent_id="local-test",
            idempotency_key="telegram:message:100",
            title="Synthetic local proof",
        )
        self.assertTrue(result["created"])
        task = result["task"]
        self.assertEqual(task["state"], "received")
        self.assertEqual(task["agent_id"], "local-test")
        events = runtime.list_events(task["task_id"])
        self.assertEqual([event["event_type"] for event in events], ["task.created"])

    def test_task_and_events_survive_runtime_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "runtime.sqlite3"
            first = TaskRuntime(db)
            task = first.create_or_get_task("local-test", "reopen-key", "Persistence proof")["task"]
            first.transition(task["task_id"], "briefing", "persist this transition")
            first.close()
            reopened = TaskRuntime(db)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.get_task(task["task_id"])["state"], "briefing")
            self.assertEqual([event["event_type"] for event in reopened.list_events(task["task_id"])], ["task.created", "task.transitioned"])

    def test_duplicate_trigger_returns_existing_task_without_duplicate_event(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        first = runtime.create_or_get_task("local-test", "duplicate-key", "First")
        second = runtime.create_or_get_task("local-test", "duplicate-key", "Ignored duplicate")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["task"]["task_id"], second["task"]["task_id"])
        self.assertEqual(len(runtime.list_events(first["task"]["task_id"])), 1)

    def test_valid_transitions_append_events_and_invalid_transition_fails_closed(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        task = runtime.create_or_get_task("local-test", "state-key", "State proof")["task"]
        runtime.transition(task["task_id"], "briefing", "brief created")
        runtime.transition(task["task_id"], "ready_to_build", "approved brief")
        runtime.transition(task["task_id"], "building", "local code starts")
        self.assertEqual(runtime.get_task(task["task_id"])["state"], "building")
        self.assertEqual(len(runtime.list_events(task["task_id"])), 4)
        with self.assertRaises(TaskRuntimeError):
            runtime.transition(task["task_id"], "completed", "cannot skip verification")
        self.assertEqual(runtime.get_task(task["task_id"])["state"], "building")

    def test_invalid_approval_wait_fails_without_mutating_task_metadata(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        task = runtime.create_or_get_task("local-test", "invalid-wait", "Invalid wait proof")["task"]
        with self.assertRaises(TaskRuntimeError):
            runtime.await_approval(task["task_id"], "must not be recorded")
        unchanged = runtime.get_task(task["task_id"])
        self.assertEqual(unchanged["state"], "received")
        self.assertEqual(unchanged["metadata"], {})
        self.assertEqual([event["event_type"] for event in runtime.list_events(task["task_id"])], ["task.created"])

    def test_approval_wait_blocks_consequential_action_until_approval(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        task = runtime.create_or_get_task("local-test", "approval-key", "Approval proof")["task"]
        runtime.transition(task["task_id"], "briefing", "brief")
        runtime.transition(task["task_id"], "ready_to_build", "ready")
        runtime.transition(task["task_id"], "building", "build")
        runtime.transition(task["task_id"], "verifying", "verified")
        premature = runtime.attempt_action(task["task_id"], "send_message", consequential=True)
        self.assertEqual(premature, {"status": "blocked", "reason": "state_not_authorized", "action": "send_message"})
        runtime.await_approval(task["task_id"], "real recipient send")
        blocked = runtime.attempt_action(task["task_id"], "send_message", consequential=True)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "awaiting_approval")
        runtime.approve(task["task_id"], "test-approver")
        allowed = runtime.attempt_action(task["task_id"], "send_message", consequential=True)
        self.assertEqual(allowed["status"], "allowed")
        self.assertEqual(runtime.get_task(task["task_id"])["state"], "shipping")

    def test_child_task_retains_parent_lineage(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        parent = runtime.create_or_get_task("local-test", "parent", "Parent")["task"]
        child = runtime.create_child_task(parent["task_id"], "local-test", "child", "Child")
        self.assertEqual(child["parent_task_id"], parent["task_id"])
        self.assertEqual(runtime.get_task(child["task_id"])["parent_task_id"], parent["task_id"])

    def test_json_ledger_import_is_read_only_and_creates_inspectable_legacy_task(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        source = Path(tmp.name) / "legacy-ledger.json"
        source.write_text(json.dumps({"version": 1, "tasks": {
            "legacy-001": {"task_id": "legacy-001", "title": "Legacy task", "status": "completed", "origin": "test"}
        }}))
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        summary = runtime.import_json_ledger(source, agent_id="local-test")
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(summary, {"imported": 1, "skipped": 0})
        imported = runtime.get_task("legacy-001")
        self.assertEqual(imported["state"], "completed")
        self.assertEqual(imported["metadata"]["legacy_import"], True)

    def test_dry_run_has_no_external_side_effects_and_proves_core_lifecycle(self) -> None:
        tmp, runtime = self.make_runtime()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(runtime.close)
        evidence = runtime.run_dry_run("local-test")
        self.assertEqual(evidence["external_side_effects"], [])
        self.assertTrue(evidence["duplicate_suppressed"])
        self.assertEqual(evidence["blocked_action"]["status"], "blocked")
        self.assertEqual(evidence["allowed_action"]["status"], "allowed")
        self.assertEqual(evidence["final_state"], "completed")

    def test_dry_run_cli_returns_parseable_evidence(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "dry-run", "--agent", "local-test"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = json.loads(completed.stdout)
        self.assertEqual(evidence["external_side_effects"], [])
        self.assertTrue(evidence["duplicate_suppressed"])
        self.assertEqual(evidence["final_state"], "completed")


if __name__ == "__main__":
    unittest.main()
