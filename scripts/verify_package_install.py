#!/usr/bin/env python3
"""Verify a multi-skill Hermes package install against the local repo manifest.

The script is intentionally generic and public-safe: it has no hard-coded private
hosts. For private fleets, pass a JSON config file outside the repo, e.g.
`--config ~/.hermes/brief_me_package_targets.json`.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]

REMOTE_CHECK = r'''
import argparse, hashlib, json
from pathlib import Path
SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]

def sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None

ap = argparse.ArgumentParser()
ap.add_argument('--agent', required=True)
ap.add_argument('--profile-root', default='~/.hermes')
ap.add_argument('--expected-json', required=True)
args = ap.parse_args()
expected = json.loads(args.expected_json)
root = Path(args.profile_root).expanduser()
base = root / 'skills' / 'productivity'
out = {'agent': args.agent, 'profile_root': str(root), 'skills': {}, 'all_ok': True}
for name in SKILLS:
    p = base / name / 'SKILL.md'
    digest = sha(p) if p.exists() else None
    ok = bool(p.exists()) and digest == expected.get(name)
    out['skills'][name] = {
        'exists': bool(p.exists()),
        'bytes': p.stat().st_size if p.exists() else 0,
        'sha256': digest,
        'expected_sha256': expected.get(name),
        'ok': ok,
    }
    out['all_ok'] = out['all_ok'] and ok
print(json.dumps(out, ensure_ascii=False, indent=2))
'''


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def repo_manifest(repo_root: Path) -> dict[str, str | None]:
    base = repo_root / "skills" / "productivity"
    return {name: sha256(base / name / "SKILL.md") for name in SKILLS}


def check_local(agent: str, profile_root: str, expected: dict[str, str | None]) -> dict[str, Any]:
    root = Path(profile_root).expanduser()
    base = root / "skills" / "productivity"
    out: dict[str, Any] = {"agent": agent, "profile_root": str(root), "skills": {}, "all_ok": True}
    for name in SKILLS:
        p = base / name / "SKILL.md"
        digest = sha256(p) if p.exists() else None
        ok = bool(p.exists()) and digest == expected.get(name)
        out["skills"][name] = {
            "exists": bool(p.exists()),
            "bytes": p.stat().st_size if p.exists() else 0,
            "sha256": digest,
            "expected_sha256": expected.get(name),
            "ok": ok,
        }
        out["all_ok"] = bool(out["all_ok"]) and ok
    return out


def check_ssh(target: dict[str, Any], expected: dict[str, str | None], timeout: int) -> dict[str, Any]:
    agent = str(target["agent"])
    ssh_target = str(target["ssh_target"])
    profile_root = str(target.get("profile_root") or "~/.hermes")
    mode = str(target.get("mode") or "posix")
    encoded = base64.b64encode(REMOTE_CHECK.encode()).decode()
    py = f"import base64; exec(base64.b64decode({encoded!r}))"
    parts = [
        "python3",
        "-c",
        py,
        "--agent",
        agent,
        "--profile-root",
        profile_root,
        "--expected-json",
        json.dumps(expected, separators=(",", ":")),
    ]
    posix_remote = shlex.join(parts)
    remote_cmd = "wsl.exe sh -lc " + shlex.quote(posix_remote) if mode == "wsl" else posix_remote
    p = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", ssh_target, remote_cmd],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if p.returncode != 0:
        return {"agent": agent, "all_ok": False, "error": (p.stderr or p.stdout)[-1200:] or f"ssh exit {p.returncode}"}
    try:
        return json.loads(p.stdout)
    except Exception as exc:
        return {"agent": agent, "all_ok": False, "error": f"json parse failed: {type(exc).__name__}: {exc}", "raw_tail": p.stdout[-1000:]}


def load_targets(args: argparse.Namespace) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    if args.config:
        data = json.loads(Path(args.config).expanduser().read_text())
        targets.extend(data.get("targets", data if isinstance(data, list) else []))
    for item in args.target_json or []:
        targets.append(json.loads(item))
    if not targets:
        targets.append({"agent": args.local_agent_name, "type": "local", "profile_root": args.local_profile_root})
    return targets


def summarize(result: dict[str, Any]) -> str:
    lines = []
    lines.append(f"package_integrity={result['all_ok']} commit={result['repo_commit']}")
    for agent in result["targets"]:
        ok_count = sum(1 for item in agent.get("skills", {}).values() if item.get("ok"))
        status = "OK" if agent.get("all_ok") else "DRIFT"
        if agent.get("error"):
            status = "ERROR"
        lines.append(f"{agent.get('agent')}: {status} {ok_count}/{len(SKILLS)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(Path.home() / "brief-me"))
    ap.add_argument("--config", help="JSON file containing {'targets': [...]} or a list of target objects")
    ap.add_argument("--target-json", action="append", help="Target object JSON. Fields: agent,type=local|ssh,profile_root,ssh_target,mode")
    ap.add_argument("--local-agent-name", default="local")
    ap.add_argument("--local-profile-root", default="~/.hermes")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-fail", action="store_true", help="Exit 0 even when drift/errors are found")
    ap.add_argument("--timeout", type=int, default=90)
    args = ap.parse_args()

    repo_root = Path(args.repo_root).expanduser()
    expected = repo_manifest(repo_root)
    missing = [name for name, digest in expected.items() if not digest]
    if missing:
        print(json.dumps({"all_ok": False, "error": "missing repo skills", "missing": missing}, indent=2), file=sys.stderr)
        return 2

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
    targets = load_targets(args)
    checked = []
    for target in targets:
        kind = target.get("type", "local")
        if kind == "local":
            checked.append(check_local(str(target.get("agent", "local")), str(target.get("profile_root", "~/.hermes")), expected))
        elif kind == "ssh":
            checked.append(check_ssh(target, expected, args.timeout))
        else:
            checked.append({"agent": target.get("agent", "unknown"), "all_ok": False, "error": f"unsupported target type: {kind}"})

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo_root": str(repo_root),
        "repo_commit": commit,
        "expected_sha256": expected,
        "targets": checked,
        "all_ok": all(bool(t.get("all_ok")) for t in checked),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else summarize(result))
    return 0 if (result["all_ok"] or args.no_fail) else 2


if __name__ == "__main__":
    raise SystemExit(main())
