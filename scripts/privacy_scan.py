#!/usr/bin/env python3
"""Fail closed when a tracked/staged public release contains likely private data.

The scanner reports only category, file/ref, and line number — never the matching
value. Add organization-specific terms through an external deny-terms file rather
than committing them to the repository.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

BUILTIN_PATTERNS = {
    "email": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    "chat_id": re.compile(r"\b-?100\d{7,}\b"),
    "private_key": re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    "credential_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"
    ),
    "provider_token": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,})\b"),
    "credential_url": re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s/@]+:[^\s/@]+@"),
    "android_private_path": re.compile("/data" + "/data/com" + r"\.termux|/storage" + "/emulated/0"),
}
ALLOWED_EMAILS = {"example@example.com", "user@example.com"}
ALLOWED_NOREPLY_SUFFIXES = ("@users.noreply.github.com", "@noreply.github.com")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL)


def tracked_files(repo: Path) -> list[Path]:
    return [repo / item for item in git(repo, "ls-files").splitlines()]


def deny_patterns(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    result = []
    for term in terms:
        cleaned = term.strip()
        if cleaned and not cleaned.startswith("#"):
            result.append(("deny_term", re.compile(re.escape(cleaned), re.IGNORECASE)))
    return result


def read_terms(args: argparse.Namespace) -> list[str]:
    terms = list(args.deny_term or [])
    if args.deny_terms_file:
        terms.extend(Path(args.deny_terms_file).expanduser().read_text().splitlines())
    return terms


def scan_text(label: str, text: str, extras: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for kind, pattern in [*BUILTIN_PATTERNS.items(), *extras]:
        for match in pattern.finditer(text):
            value = match.group(0).lower()
            if kind == "email" and value in ALLOWED_EMAILS:
                continue
            hits.append({"kind": kind, "location": label, "line": text.count("\n", 0, match.start()) + 1})
    return hits


def scan_tree(repo: Path, extras: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for path in tracked_files(repo):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        hits.extend(scan_text(str(path.relative_to(repo)), raw.decode(errors="ignore"), extras))
    return hits


def scan_staged(repo: Path, extras: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, object]]:
    diff = git(repo, "diff", "--cached", "--no-ext-diff", "--unified=0")
    return scan_text("staged diff", diff, extras)


def scan_history(repo: Path, extras: list[tuple[str, re.Pattern[str]]]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    commits = git(repo, "rev-list", "--all").splitlines()
    for commit in commits:
        identities = git(repo, "show", "-s", "--format=%ae%n%ce", commit).splitlines()
        for email in identities:
            if email and not email.lower().endswith(ALLOWED_NOREPLY_SUFFIXES):
                hits.append({"kind": "commit_identity", "location": commit[:12], "line": 0})
        for name in git(repo, "ls-tree", "-r", "--name-only", commit).splitlines():
            raw = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
            if b"\x00" not in raw:
                hits.extend(scan_text(f"{commit[:12]}:{name}", raw.decode(errors="ignore"), extras))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--staged", action="store_true", help="Scan the staged diff as well as the tracked tree")
    parser.add_argument("--history", action="store_true", help="Scan all reachable commits and commit identities")
    parser.add_argument("--deny-term", action="append", help="Additional case-insensitive prohibited term; repeatable")
    parser.add_argument("--deny-terms-file", help="External newline-delimited prohibited terms file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root).expanduser().resolve()
    extras = deny_patterns(read_terms(args))
    hits = scan_tree(repo, extras)
    if args.staged:
        hits.extend(scan_staged(repo, extras))
    if args.history:
        hits.extend(scan_history(repo, extras))
    result = {"ok": not hits, "hit_count": len(hits), "hits": hits}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"privacy_scan={'PASS' if result['ok'] else 'FAIL'} hits={result['hit_count']}")
        for hit in hits:
            print(f"{hit['kind']}: {hit['location']}:{hit['line']}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
