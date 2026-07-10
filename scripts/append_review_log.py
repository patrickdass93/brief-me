#!/usr/bin/env python3
"""Append a machine-readable local review record for the brief-me package cron."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-path", default=str(Path.home() / ".hermes" / "state" / "brief_me_package_reviews.jsonl"))
    ap.add_argument("--decision", required=True, choices=["no_change", "auto_edit", "proposal", "drift_fix", "error"])
    ap.add_argument("--repo-commit", required=True)
    ap.add_argument("--integrity", required=True, help="Short integrity summary, e.g. '5/5 targets OK'")
    ap.add_argument("--evidence-summary", action="append", default=[])
    ap.add_argument("--changes", default="none")
    ap.add_argument("--next", default="None")
    ap.add_argument("--input-json", help="Optional JSON object to merge into the record")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    record: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "decision": args.decision,
        "repo_commit": args.repo_commit,
        "integrity": args.integrity,
        "evidence_summary": args.evidence_summary,
        "changes": args.changes,
        "next": args.next,
    }
    if args.input_json:
        extra = json.loads(Path(args.input_json).expanduser().read_text())
        if not isinstance(extra, dict):
            raise SystemExit("--input-json must point to a JSON object")
        record.update(extra)

    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    if args.dry_run:
        print(line)
        return 0

    path = Path(args.log_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(json.dumps({"log_path": str(path), "bytes_appended": len(line) + 1}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
