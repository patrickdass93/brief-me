#!/usr/bin/env python3
"""Small, redaction-preserving Google Docs adapter for brief-me stage records."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class GoogleDocsError(RuntimeError):
    """Raised when gog cannot create, read, or append a task-review document."""


def _run(*args: str) -> str:
    completed = subprocess.run(
        ["gog", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "gog failed"
        raise GoogleDocsError(detail)
    return completed.stdout


def create_task_document(folder_id: str, title: str, template_path: Path) -> dict[str, Any]:
    """Create one private task document from a local template in the supplied folder."""
    output = _run(
        "docs",
        "create",
        title,
        "--parent",
        folder_id,
        "--file",
        str(template_path),
        "--json",
        "--results-only",
        "--no-input",
    )
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise GoogleDocsError("gog docs create returned invalid JSON") from exc
    document_id = data.get("documentId") or data.get("id")
    if not isinstance(document_id, str) or not document_id:
        raise GoogleDocsError("gog docs create did not return a document ID")
    return {"document_id": document_id, "raw": data}


def append_task_document(document_id: str, markdown: str) -> None:
    """Append report text without sending it through a shell or retaining it locally."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(markdown)
        path = Path(handle.name)
    try:
        _run("docs", "write", document_id, "--append", "--file", str(path), "--no-input")
    finally:
        path.unlink(missing_ok=True)


def read_task_document(document_id: str) -> str:
    """Read plain text back for marker verification."""
    return _run("docs", "cat", document_id, "--plain", "--no-input")


def document_url(document_id: str) -> str:
    return f"https://docs.google.com/document/d/{document_id}/edit"
