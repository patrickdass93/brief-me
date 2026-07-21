#!/usr/bin/env python3
"""Read-only Task Runtime readiness audit for local Hermes roots and SSH targets.

Private target routing is supplied by `--config` outside the repository. The probe
reads only safe filesystem/runtime metadata; it does not read private config
contents, create paths, install packages, invoke models, or alter remote hosts.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def audit_local_root(agent: str, profile_root: Path) -> dict[str, Any]:
    """Return safe metadata for one Hermes root without reading private contents."""
    root = profile_root.expanduser()
    skills: dict[str, Any] = {}
    for name in SKILLS:
        path = root / "skills" / "productivity" / name / "SKILL.md"
        skills[name] = {"exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}
    runtime_path = root / "runtime" / "task-runtime" / "task_runtime.py"
    state_path = root / "state"
    accessible = state_path if state_path.exists() else root
    report = {
        "agent": agent,
        "profile_root": str(root),
        "root_present": root.is_dir(),
        "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
        "hermes_cli_present": bool(shutil.which("hermes")),
        "skills": skills,
        "runtime": {"exists": runtime_path.is_file(), "sha256": sha256(runtime_path) if runtime_path.is_file() else None},
        "ledger_present": (root / "scripts" / "agent_task_ledger.py").is_file(),
        "watchdog_present": (root / "scripts" / "agent_task_watchdog.py").is_file(),
        "state_dir_present": state_path.is_dir(),
        "state_path_accessible": root.is_dir() and os.access(accessible, os.R_OK | os.X_OK),
        "private_stage_config_present": (root / "brief_me_stage_reviews.private.json").is_file(),
    }
    skills_complete = all(item["exists"] for item in skills.values())
    if not report["root_present"] or not report["state_path_accessible"]:
        report["status"] = "blocked"
    elif not skills_complete or not report["hermes_cli_present"]:
        report["status"] = "drift"
    else:
        report["status"] = "ready_for_inactive_install"
    return report


REMOTE_PROBE = r'''
import base64, sys
from pathlib import Path
payload = base64.b64decode(sys.argv[1]).decode()
namespace = {'__name__': 'audit_runtime_remote'}
exec(payload, namespace)
result = namespace['audit_local_root'](sys.argv[2], Path(sys.argv[3]).expanduser())
import json
print(json.dumps(result, ensure_ascii=False))
'''


def remote_audit_payload() -> str:
    # Keep the standalone remote implementation dependency-free and read-only.
    body = '''
import hashlib, os, shutil, sqlite3, sys
from pathlib import Path
SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]
def sha256(path):
    try: return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError: return None
def audit_local_root(agent, root):
    skills = {}
    for name in SKILLS:
        p = root / "skills" / "productivity" / name / "SKILL.md"
        skills[name] = {"exists": p.is_file(), "sha256": sha256(p) if p.is_file() else None}
    runtime = root / "runtime" / "task-runtime" / "task_runtime.py"
    state = root / "state"; accessible = state if state.exists() else root
    report = {"agent": agent, "profile_root": str(root), "root_present": root.is_dir(), "python_version": sys.version.split()[0], "sqlite_version": sqlite3.sqlite_version, "hermes_cli_present": bool(shutil.which("hermes")), "skills": skills, "runtime": {"exists": runtime.is_file(), "sha256": sha256(runtime) if runtime.is_file() else None}, "ledger_present": (root / "scripts" / "agent_task_ledger.py").is_file(), "watchdog_present": (root / "scripts" / "agent_task_watchdog.py").is_file(), "state_dir_present": state.is_dir(), "state_path_accessible": root.is_dir() and os.access(accessible, os.R_OK | os.X_OK), "private_stage_config_present": (root / "brief_me_stage_reviews.private.json").is_file()}
    skills_complete = all(item["exists"] for item in skills.values())
    if not report["root_present"] or not report["state_path_accessible"]:
        report["status"] = "blocked"
    elif not skills_complete or not report["hermes_cli_present"]:
        report["status"] = "drift"
    else:
        report["status"] = "ready_for_inactive_install"
    return report
'''
    return base64.b64encode(body.encode()).decode()


def audit_ssh(target: dict[str, Any], timeout: int) -> dict[str, Any]:
    agent = str(target["agent"])
    profile_root = str(target.get("profile_root") or "~/.hermes")
    mode = str(target.get("mode") or "posix")
    encoded_probe = base64.b64encode(REMOTE_PROBE.encode()).decode()
    payload = remote_audit_payload()
    python = f"import base64; exec(base64.b64decode({encoded_probe!r}))"
    command = shlex.join(["python3", "-c", python, payload, agent, profile_root])
    if mode == "wsl":
        command = "wsl.exe sh -lc " + shlex.quote(command)
    elif mode != "posix":
        return {"agent": agent, "status": "blocked", "error": f"unsupported target mode: {mode}"}
    try:
        ssh_args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
        if target.get("ssh_port"):
            ssh_args.extend(["-p", str(target["ssh_port"])])
        result = subprocess.run(ssh_args + [str(target["ssh_target"]), command], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"agent": agent, "status": "blocked", "error": "ssh timeout"}
    if result.returncode:
        return {"agent": agent, "status": "blocked", "error": (result.stderr or result.stdout)[-500:] or f"ssh exit {result.returncode}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"agent": agent, "status": "blocked", "error": "remote audit returned invalid JSON"}


def load_targets(config: Path) -> list[dict[str, Any]]:
    data = json.loads(config.expanduser().read_text())
    targets = data.get("targets", data if isinstance(data, list) else [])
    if not isinstance(targets, list) or not targets:
        raise ValueError("config must contain a non-empty targets list")
    return [dict(item) for item in targets]


def audit_target(target: dict[str, Any], timeout: int) -> dict[str, Any]:
    kind = str(target.get("type", "local"))
    if kind == "local":
        return audit_local_root(str(target.get("agent", "local")), Path(str(target.get("profile_root", "~/.hermes"))))
    if kind == "ssh":
        return audit_ssh(target, timeout)
    return {"agent": str(target.get("agent", "unknown")), "status": "blocked", "error": f"unsupported target type: {kind}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Private target JSON outside the repository")
    parser.add_argument("--local-agent", default="local")
    parser.add_argument("--local-profile-root", default="~/.hermes")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", help="Optional local JSON output path")
    args = parser.parse_args()
    targets = load_targets(Path(args.config)) if args.config else [{"agent": args.local_agent, "type": "local", "profile_root": args.local_profile_root}]
    result = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "read_only": True, "targets": [audit_target(target, args.timeout) for target in targets]}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).expanduser().write_text(text + "\n")
    return 0 if all(item.get("status") != "blocked" for item in result["targets"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
