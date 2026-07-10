#!/usr/bin/env python3
"""Deploy the four-skill brief-me package from a local repo to configured targets.

This helper is intentionally generic and public-safe: it has no hard-coded hosts,
credentials, or profile paths. Pass a private JSON config outside the repository:

    scripts/deploy_package_install.py --config ~/.hermes/brief_me_package_targets.json

Each deployment creates a timestamped backup under the target profile root before
replacing only `skills/productivity/{brief-me,build-me,ship-me,maintain-me}`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]


def load_targets(config_path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(config_path).expanduser().read_text())
    targets = data.get("targets", data if isinstance(data, list) else [])
    if not isinstance(targets, list) or not targets:
        raise ValueError("config must contain a non-empty targets list")
    return [dict(item) for item in targets]


def source_root(repo_root: Path) -> Path:
    root = repo_root / "skills" / "productivity"
    missing = [name for name in SKILLS if not (root / name / "SKILL.md").is_file()]
    if missing:
        raise FileNotFoundError(f"missing package skills in repo: {', '.join(missing)}")
    return root


def archive_bytes(source: Path) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name in SKILLS:
            archive.add(source / name, arcname=name)
    return stream.getvalue()


def backup_name() -> str:
    return f"brief-me-package-{time.strftime('%Y%m%d-%H%M%S')}"


def expand_local(path_text: str) -> Path:
    return Path(path_text).expanduser()


def deploy_local(target: dict[str, Any], source: Path, dry_run: bool) -> dict[str, Any]:
    agent = str(target.get("agent", "local"))
    root = expand_local(str(target.get("profile_root", "~/.hermes")))
    destination = root / "skills" / "productivity"
    backup = root / "backups" / backup_name()
    if dry_run:
        return {"agent": agent, "ok": True, "dry_run": True, "installed": len(SKILLS)}
    destination.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=False)
    for name in SKILLS:
        existing = destination / name
        if existing.exists():
            shutil.copytree(existing, backup / name, symlinks=True)
        shutil.rmtree(existing, ignore_errors=True)
        shutil.copytree(source / name, existing, symlinks=True)
    return {"agent": agent, "ok": True, "installed": len(SKILLS), "backup_created": True}


def remote_root_expr(profile_root: str) -> str:
    if profile_root == "~":
        return "$HOME"
    if profile_root.startswith("~/"):
        return "$HOME/" + profile_root[2:]
    return profile_root


def remote_install_command(profile_root: str, stamp: str) -> str:
    root = remote_root_expr(profile_root)
    skills = " ".join(SKILLS)
    # Keep this POSIX script semicolon-safe so the WSL transport can pass it as a
    # single `sh -lc` argument without changing loop/conditional grammar.
    return (
        f'set -eu; ROOT="{root}"; DEST="$ROOT/skills/productivity"; '
        f'BACKUP="$ROOT/backups/brief-me-package-{stamp}"; '
        f'STAGE="$ROOT/.brief-me-package-stage-{stamp}-$$"; '
        'cleanup() { rm -rf "$STAGE"; }; trap cleanup EXIT; '
        'mkdir -p "$DEST" "$BACKUP" "$STAGE"; tar -xf - -C "$STAGE"; '
        f'for NAME in {skills}; do '
        'test -f "$STAGE/$NAME/SKILL.md"; '
        'if test -e "$DEST/$NAME"; then cp -a "$DEST/$NAME" "$BACKUP/$NAME"; fi; '
        'rm -rf "$DEST/$NAME"; mv "$STAGE/$NAME" "$DEST/$NAME"; '
        f'done; printf "installed=%s backup_created=true\\n" "{len(SKILLS)}"'
    )

def deploy_ssh(target: dict[str, Any], archive: bytes, timeout: int, dry_run: bool) -> dict[str, Any]:
    agent = str(target.get("agent", "remote"))
    ssh_target = str(target["ssh_target"])
    profile_root = str(target.get("profile_root") or "~/.hermes")
    mode = str(target.get("mode") or "posix")
    if dry_run:
        return {"agent": agent, "ok": True, "dry_run": True, "installed": len(SKILLS)}

    command = remote_install_command(profile_root, time.strftime("%Y%m%d-%H%M%S"))
    if mode == "wsl":
        # Windows OpenSSH invokes the remote command through an outer shell before
        # `wsl.exe` starts its own POSIX shell. Use one double-quoted argument and
        # escape it for the outer shell; nested shlex single quotes break on this hop.
        one_line = command.replace("\n", "; ")
        escaped = (
            one_line.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        remote_command = f'wsl.exe sh -lc "{escaped}"'
    elif mode == "posix":
        remote_command = command
    else:
        return {"agent": agent, "ok": False, "error": f"unsupported target mode: {mode}"}

    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            ssh_target,
            remote_command,
        ],
        input=archive,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return {
            "agent": agent,
            "ok": False,
            "error": (proc.stderr or proc.stdout).decode(errors="replace")[-400:] or f"ssh exit {proc.returncode}",
        }
    return {"agent": agent, "ok": True, "installed": len(SKILLS), "backup_created": True}


def deploy_target(target: dict[str, Any], source: Path, archive: bytes, timeout: int, dry_run: bool) -> dict[str, Any]:
    kind = str(target.get("type", "local"))
    try:
        if kind == "local":
            return deploy_local(target, source, dry_run)
        if kind == "ssh":
            return deploy_ssh(target, archive, timeout, dry_run)
        return {"agent": str(target.get("agent", "unknown")), "ok": False, "error": f"unsupported target type: {kind}"}
    except Exception as exc:
        return {"agent": str(target.get("agent", "unknown")), "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path.home() / "brief-me"))
    parser.add_argument("--config", required=True, help="Private JSON config with target definitions")
    parser.add_argument("--agent", action="append", help="Deploy only a named target; repeat to select several")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root).expanduser()
    source = source_root(repo)
    targets = load_targets(args.config)
    if args.agent:
        wanted = set(args.agent)
        targets = [target for target in targets if str(target.get("agent")) in wanted]
        if not targets:
            parser.error("no configured targets matched --agent")
    bundle = archive_bytes(source)
    results = [deploy_target(target, source, bundle, args.timeout, args.dry_run) for target in targets]
    output = {
        "repo_root": str(repo),
        "target_count": len(results),
        "all_ok": all(bool(item.get("ok")) for item in results),
        "results": results,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"{item['agent']}: {'OK' if item['ok'] else 'ERROR'}")
    return 0 if output["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
