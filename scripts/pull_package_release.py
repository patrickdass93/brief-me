#!/usr/bin/env python3
"""Fetch a pinned public package release into a local checkout without installing it.

This is an opt-in source acquisition helper. It never invokes the package installer,
creates no runtime database, and activates no agent behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class PullError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], cwd: Path | None = None) -> str:
    process = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        raise PullError((process.stderr or process.stdout).strip() or f"command failed: {args[0]}")
    return process.stdout.strip()


def verify_manifest(checkout: Path, ref: str) -> dict[str, Any]:
    path = checkout / "release-manifest.json"
    if not path.is_file():
        raise PullError("release-manifest.json is missing")
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1:
        raise PullError("unsupported release manifest schema")
    if data.get("version") != ref:
        raise PullError("release manifest version does not match requested ref")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise PullError("release manifest has no file hashes")
    for relative, expected in files.items():
        candidate = checkout / relative
        if not candidate.is_file() or sha256(candidate) != expected:
            raise PullError(f"release manifest hash mismatch for {relative}")
    return {"version": data["version"], "file_count": len(files)}


def _matching_existing_checkout(repo_url: str, ref: str, expected_commit: str, checkout: Path) -> dict[str, Any] | None:
    if not checkout.exists():
        return None
    if not (checkout / ".git").is_dir():
        raise PullError("checkout exists but is not a Git checkout")
    existing_remote = run(["git", "remote", "get-url", "origin"], checkout)
    if existing_remote != repo_url:
        raise PullError("existing checkout origin does not match requested repository")
    commit = run(["git", "rev-parse", "HEAD"], checkout)
    if commit != expected_commit:
        return None
    manifest = verify_manifest(checkout, ref)
    return {"ok": True, "already_verified": True, "checkout": str(checkout), "commit": commit, "manifest": manifest, "installed_runtime": False}


def pull_release(repo_url: str, ref: str, expected_commit: str, checkout: Path, dry_run: bool) -> dict[str, Any]:
    if not repo_url or not ref or not expected_commit:
        raise PullError("repo_url, ref, and expected_commit are required")
    checkout = checkout.expanduser()
    if dry_run:
        return {"ok": True, "dry_run": True, "repo_url": repo_url, "ref": ref, "expected_commit": expected_commit, "checkout": str(checkout), "installed_runtime": False}
    existing = _matching_existing_checkout(repo_url, ref, expected_commit, checkout)
    if existing:
        return existing
    if checkout.exists():
        raise PullError("existing checkout is not the expected pinned release; choose a versioned checkout path instead of replacing it")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=checkout.parent, prefix=f".{checkout.name}.stage-") as temporary:
        stage = Path(temporary) / "checkout"
        run(["git", "clone", "--no-checkout", repo_url, str(stage)])
        run(["git", "fetch", "--tags", "origin", ref], stage)
        run(["git", "checkout", "--detach", ref], stage)
        commit = run(["git", "rev-parse", "HEAD"], stage)
        if commit != expected_commit:
            raise PullError("requested ref did not resolve to the expected commit")
        manifest = verify_manifest(stage, ref)
        shutil.move(str(stage), str(checkout))
    return {"ok": True, "already_verified": False, "checkout": str(checkout), "commit": expected_commit, "manifest": manifest, "installed_runtime": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--ref", required=True, help="Immutable public tag, for example v0.1.0")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--checkout", required=True, help="Versioned local source-checkout path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = pull_release(args.repo_url, args.ref, args.expected_commit, Path(args.checkout), args.dry_run)
    except (PullError, OSError, json.JSONDecodeError) as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "installed_runtime": False}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else ("OK" if result.get("ok") else f"ERROR: {result.get('error')}"))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
