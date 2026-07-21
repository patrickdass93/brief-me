#!/usr/bin/env python3
"""Fail-closed local privacy preflight for a candidate public Git release.

Scans tracked tree, staged diff, reachable history, and commit identity metadata.
It reports only category/ref/path metadata, never the matching secret/term value.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "generic_api_key": re.compile(rb"(?:sk-[A-Za-z0-9]{20,}|rk_(?:live|test)_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,})"),
    "telegram_token": re.compile(rb"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    "ipv4_address": re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


def scan_bytes(data: bytes, reference: str, deny_terms: list[bytes] | None = None) -> list[dict[str, str]]:
    findings = [{"category": category, "reference": reference} for category, pattern in PATTERNS.items() if pattern.search(data)]
    for term in deny_terms or []:
        if term and term.lower() in data.lower():
            findings.append({"category": "deny_term", "reference": reference})
    return findings


def run(args: list[str], repo: Path) -> bytes:
    result = subprocess.run(args, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).decode(errors="replace").strip() or "git command failed")
    return result.stdout


def deny_terms(path: Path) -> list[bytes]:
    return [line.strip().encode() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def tracked_tree(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for raw in run(["git", "ls-files", "-z"], repo).split(b"\0"):
        if not raw:
            continue
        relative = raw.decode(errors="replace")
        try:
            findings.extend(scan_bytes((repo / relative).read_bytes(), f"tracked:{relative}", terms))
        except OSError:
            findings.append({"category": "unreadable_tracked_file", "reference": f"tracked:{relative}"})
    return findings


def staged_diff(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    return scan_bytes(run(["git", "diff", "--cached", "--binary"], repo), "staged_diff", terms)


def reachable_history(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    objects = run(["git", "rev-list", "--objects", "--all"], repo).splitlines()
    seen: set[bytes] = set()
    for item in objects:
        object_id = item.split(maxsplit=1)[0]
        if object_id in seen:
            continue
        seen.add(object_id)
        object_type = run(["git", "cat-file", "-t", object_id.decode()], repo).strip()
        if object_type != b"blob":
            continue
        findings.extend(scan_bytes(run(["git", "cat-file", "-p", object_id.decode()], repo), f"history_blob:{object_id.decode()[:12]}", terms))
    metadata = run(["git", "log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce"], repo)
    for row in metadata.splitlines():
        findings.extend(scan_bytes(row, "commit_identity", terms))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--deny-terms-file", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo_root).expanduser().resolve()
    terms = deny_terms(Path(args.deny_terms_file).expanduser())
    findings = tracked_tree(repo, terms) + staged_diff(repo, terms) + reachable_history(repo, terms)
    result = {"ok": not findings, "finding_count": len(findings), "findings": findings}
    print(json.dumps(result, indent=2) if args.json else f"public_release_preflight={'PASS' if result['ok'] else 'FAIL'} findings={len(findings)}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
