#!/usr/bin/env python3
"""Create a conservative brief-me package improvement proposal.

Use this when evidence suggests a change, but the cron is not allowed to
auto-apply it because the evidence is ambiguous, one-off, structural, or policy
changing.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

VALID_SKILLS = {"brief-me", "build-me", "ship-me", "maintain-me", "package"}


def proposal_text(args: argparse.Namespace, date: str) -> str:
    return f"""# brief-me package improvement proposal — {date}

## Decision

Proposal only — not auto-applied.

## Affected skill

`{args.affected_skill}`

## Evidence summary

{args.evidence_summary.strip()}

## Suggested patch

```diff
{args.suggested_patch.strip()}
```

## Why this was not auto-applied

{args.rationale.strip()}

## Validation/deployment notes

- No skill files changed by this proposal.
- If approved later, validate all four package `SKILL.md` files before commit.
- Re-run package integrity verification after any approved change.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(Path.home() / "brief-me"))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--affected-skill", required=True, choices=sorted(VALID_SKILLS))
    ap.add_argument("--evidence-summary", required=True)
    ap.add_argument("--suggested-patch", required=True)
    ap.add_argument("--rationale", required=True)
    ap.add_argument("--dry-run", action="store_true", help="Print target path and preview without writing")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).expanduser()
    proposal_dir = repo_root / "proposals"
    path = proposal_dir / f"{args.date}-brief-me-improvement.md"
    if path.exists():
        n = 2
        while True:
            candidate = proposal_dir / f"{args.date}-brief-me-improvement-{n}.md"
            if not candidate.exists():
                path = candidate
                break
            n += 1

    text = proposal_text(args, args.date)
    if args.dry_run:
        print(json.dumps({"would_write": str(path), "bytes": len(text), "preview": text.splitlines()[:12]}, indent=2))
        return 0

    proposal_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(json.dumps({"proposal_path": str(path), "bytes": len(text)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
