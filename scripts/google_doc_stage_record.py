#!/usr/bin/env python3
"""Redaction-preserving Google Docs adapter supporting gog or gws."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class GoogleDocsError(RuntimeError):
    """Raised when the selected Google Workspace CLI cannot operate on a task Doc."""


def google_backend() -> str:
    """Choose gog/gws, honoring BRIEF_ME_GOOGLE_CLI when explicitly configured."""
    configured = os.environ.get("BRIEF_ME_GOOGLE_CLI", "auto").lower()
    if configured in {"gog", "gws"}:
        if not shutil.which(configured):
            raise GoogleDocsError(f"configured Google CLI is unavailable: {configured}")
        return configured
    for candidate in ("gog", "gws"):
        if shutil.which(candidate):
            return candidate
    raise GoogleDocsError("neither gog nor gws is available; install/authenticate one Google Workspace CLI")


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"{command[0]} failed"
        raise GoogleDocsError(detail)
    return completed.stdout


def _json(command: list[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(_run(command))
    except json.JSONDecodeError as exc:
        raise GoogleDocsError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise GoogleDocsError(f"{label} returned a non-object JSON value")
    return value


def create_task_document(folder_id: str, title: str, template_path: Path) -> dict[str, Any]:
    """Create one private task Doc in the configured folder using gog or gws."""
    backend = google_backend()
    if backend == "gog":
        data = _json(["gog", "docs", "create", title, "--parent", folder_id, "--file", str(template_path), "--json", "--results-only", "--no-input"], "gog docs create")
        document_id = data.get("documentId") or data.get("id")
    else:
        data = _json(["gws", "docs", "documents", "create", "--json", json.dumps({"title": title})], "gws docs documents create")
        document_id = data.get("documentId")
        if isinstance(document_id, str) and document_id:
            _run(["gws", "drive", "files", "update", "--params", json.dumps({"fileId": document_id, "addParents": folder_id}), "--json", "{}"])
            append_task_document(document_id, template_path.read_text(encoding="utf-8"))
    if not isinstance(document_id, str) or not document_id:
        raise GoogleDocsError(f"{backend} document creation did not return a document ID")
    return {"document_id": document_id, "raw": data, "backend": backend}


def append_task_document(document_id: str, markdown: str) -> None:
    """Append report text without shell interpolation or persistent temp artifacts."""
    backend = google_backend()
    if backend == "gws":
        _run(["gws", "docs", "+write", "--document", document_id, "--text", markdown])
        return
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(markdown)
        path = Path(handle.name)
    try:
        _run(["gog", "docs", "write", document_id, "--append", "--file", str(path), "--no-input"])
    finally:
        path.unlink(missing_ok=True)


def _gws_text(value: Any) -> str:
    if isinstance(value, dict):
        if isinstance(value.get("textRun"), dict) and isinstance(value["textRun"].get("content"), str):
            return value["textRun"]["content"]
        return "".join(_gws_text(item) for item in value.values())
    if isinstance(value, list):
        return "".join(_gws_text(item) for item in value)
    return ""


def read_task_document(document_id: str) -> str:
    """Read plain text back for canonical-marker verification."""
    if google_backend() == "gog":
        return _run(["gog", "docs", "cat", document_id, "--plain", "--no-input"])
    data = _json(["gws", "docs", "documents", "get", "--params", json.dumps({"documentId": document_id})], "gws docs documents get")
    return _gws_text(data.get("body", {}))


def document_url(document_id: str) -> str:
    return f"https://docs.google.com/document/d/{document_id}/edit"
