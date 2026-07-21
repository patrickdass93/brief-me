#!/usr/bin/env python3
"""Redaction-preserving Google Docs adapter supporting gog or gws."""
from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any


class GoogleDocsError(RuntimeError):
    """Raised when the selected Google Workspace CLI cannot operate on a task Doc."""


def _hermes_api_script_path() -> Path:
    """Return the target profile's Google API helper without reading credentials."""
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    script_path = hermes_home / "skills" / "productivity" / "google-workspace" / "scripts" / "google_api.py"
    if not script_path.is_file():
        raise GoogleDocsError("Hermes Google Workspace skill is unavailable for hermes-api backend")
    return script_path


@lru_cache(maxsize=1)
def _hermes_api_services() -> tuple[Any, Any]:
    """Load and reuse target-owned Google API clients without copying OAuth."""
    script_path = _hermes_api_script_path()
    try:
        # The Hermes helper imports a sibling module when run standalone. Make
        # that sibling visible only during import, then restore this process's
        # import search order before doing any document work.
        original_sys_path = sys.path.copy()
        sys.path.insert(0, str(script_path.parent))
        try:
            spec = importlib.util.spec_from_file_location("brief_me_hermes_google_api", script_path)
            if not spec or not spec.loader:
                raise ImportError("could not create a module spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path[:] = original_sys_path
        build_service = module.build_service
        return build_service("drive", "v3"), build_service("docs", "v1")
    except Exception as exc:
        raise GoogleDocsError(f"Hermes Google API backend is unavailable: {type(exc).__name__}") from exc


def google_backend() -> str:
    """Choose a configured Google backend without copying OAuth credentials."""
    configured = os.environ.get("BRIEF_ME_GOOGLE_CLI", "auto").lower()
    if configured in {"gog", "gws"}:
        if not shutil.which(configured):
            raise GoogleDocsError(f"configured Google CLI is unavailable: {configured}")
        return configured
    if configured == "hermes-api":
        _hermes_api_script_path()
        return configured
    for candidate in ("gog", "gws"):
        if shutil.which(candidate):
            return candidate
    try:
        _hermes_api_script_path()
        return "hermes-api"
    except GoogleDocsError:
        pass
    raise GoogleDocsError("no usable Google backend: install/authenticate gog, gws, or the Hermes Google Workspace skill")


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
    """Create one private task Doc in the configured folder using its own OAuth."""
    backend = google_backend()
    if backend == "gog":
        data = _json(["gog", "docs", "create", title, "--parent", folder_id, "--file", str(template_path), "--json", "--results-only", "--no-input"], "gog docs create")
        document_id = data.get("documentId") or data.get("id")
    elif backend == "gws":
        data = _json(["gws", "docs", "documents", "create", "--json", json.dumps({"title": title})], "gws docs documents create")
        document_id = data.get("documentId")
        if isinstance(document_id, str) and document_id:
            _run(["gws", "drive", "files", "update", "--params", json.dumps({"fileId": document_id, "addParents": folder_id}), "--json", "{}"])
            append_task_document(document_id, template_path.read_text(encoding="utf-8"))
    elif backend == "hermes-api":
        drive, docs = _hermes_api_services()
        data = drive.files().create(
            body={"name": title, "mimeType": "application/vnd.google-apps.document", "parents": [folder_id]},
            fields="id",
        ).execute()
        document_id = data.get("id")
        if isinstance(document_id, str) and document_id:
            docs.documents().batchUpdate(
                documentId=document_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": template_path.read_text(encoding="utf-8")}}]},
            ).execute()
    else:
        raise GoogleDocsError(f"unsupported Google backend: {backend}")
    if not isinstance(document_id, str) or not document_id:
        raise GoogleDocsError(f"{backend} document creation did not return a document ID")
    return {"document_id": document_id, "raw": data, "backend": backend}


def append_task_document(document_id: str, markdown: str) -> None:
    """Append report text without shell interpolation or persistent temp artifacts."""
    backend = google_backend()
    if backend == "gws":
        _run(["gws", "docs", "+write", "--document", document_id, "--text", markdown])
        return
    if backend == "hermes-api":
        _, docs = _hermes_api_services()
        document = docs.documents().get(documentId=document_id).execute()
        content = document.get("body", {}).get("content", [])
        end_index = max((item.get("endIndex", 1) for item in content if isinstance(item, dict)), default=1)
        docs.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": max(1, end_index - 1)}, "text": markdown}}]},
        ).execute()
        return
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(markdown)
        path = Path(handle.name)
    try:
        _run(["gog", "docs", "write", document_id, "--append", "--file", str(path), "--no-input"])
    finally:
        path.unlink(missing_ok=True)


def _docs_text(value: Any) -> str:
    if isinstance(value, dict):
        if isinstance(value.get("textRun"), dict) and isinstance(value["textRun"].get("content"), str):
            return value["textRun"]["content"]
        return "".join(_docs_text(item) for item in value.values())
    if isinstance(value, list):
        return "".join(_docs_text(item) for item in value)
    return ""


def read_task_document(document_id: str) -> str:
    """Read plain text back for canonical-marker verification."""
    if google_backend() == "gog":
        return _run(["gog", "docs", "cat", document_id, "--plain", "--no-input"])
    if google_backend() == "hermes-api":
        _, docs = _hermes_api_services()
        return _docs_text(docs.documents().get(documentId=document_id).execute().get("body", {}))
    data = _json(["gws", "docs", "documents", "get", "--params", json.dumps({"documentId": document_id})], "gws docs documents get")
    return _docs_text(data.get("body", {}))


def document_url(document_id: str) -> str:
    return f"https://docs.google.com/document/d/{document_id}/edit"
