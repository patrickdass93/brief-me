#!/usr/bin/env python3
"""Deploy the brief-me skill package plus its local Task Runtime to configured targets.

The tool is generic and public-safe: target routes live only in a private JSON
configuration outside the repository. `--dry-run` never writes a target.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

SKILLS = ["brief-me", "build-me", "ship-me", "maintain-me"]
RUNTIME_ARCHIVE_PATH = "runtime/task_runtime.py"
RUNTIME_INSTALL_DIR = Path("runtime") / "task-runtime"


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


def runtime_source(repo_root: Path) -> Path:
    path = repo_root / "scripts" / "task_runtime.py"
    if not path.is_file():
        raise FileNotFoundError(f"missing runtime source: {path}")
    return path


def archive_bytes(source: Path, runtime: Path | None = None) -> bytes:
    runtime = runtime or source.parents[1] / "scripts" / "task_runtime.py"
    if not runtime.is_file():
        raise FileNotFoundError(f"missing runtime source: {runtime}")
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name in SKILLS:
            archive.add(source / name, arcname=name)
        archive.add(runtime, arcname=RUNTIME_ARCHIVE_PATH)
    return stream.getvalue()


def backup_name(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


def expand_local(path_text: str) -> Path:
    return Path(path_text).expanduser()


def deploy_local(target: dict[str, Any], source: Path, runtime: Path, dry_run: bool) -> dict[str, Any]:
    agent = str(target.get("agent", "local"))
    root = expand_local(str(target.get("profile_root", "~/.hermes")))
    skills_destination = root / "skills" / "productivity"
    runtime_destination = root / RUNTIME_INSTALL_DIR
    if dry_run:
        return {"agent": agent, "ok": True, "dry_run": True, "skills_installed": len(SKILLS), "runtime_installed": True}

    skills_backup = root / "backups" / backup_name("brief-me-package")
    runtime_backup = root / "backups" / backup_name("brief-me-runtime")
    skills_destination.mkdir(parents=True, exist_ok=True)
    skills_backup.mkdir(parents=True, exist_ok=False)
    runtime_backup.mkdir(parents=True, exist_ok=False)
    for name in SKILLS:
        existing = skills_destination / name
        if existing.exists():
            shutil.copytree(existing, skills_backup / name, symlinks=True)
        shutil.rmtree(existing, ignore_errors=True)
        shutil.copytree(source / name, existing, symlinks=True)
    if runtime_destination.exists():
        shutil.copytree(runtime_destination, runtime_backup / "task-runtime", symlinks=True)
    shutil.rmtree(runtime_destination, ignore_errors=True)
    runtime_destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runtime, runtime_destination / "task_runtime.py")
    return {"agent": agent, "ok": True, "skills_installed": len(SKILLS), "runtime_installed": True, "backup_created": True}


def remote_root_expr(profile_root: str) -> str:
    if profile_root == "~":
        return "$HOME"
    if profile_root.startswith("~/"):
        return "$HOME/" + profile_root[2:]
    return profile_root


def remote_install_command(profile_root: str, stamp: str) -> str:
    root = remote_root_expr(profile_root)
    skills = " ".join(SKILLS)
    return (
        f'set -eu; ROOT="{root}"; DEST="$ROOT/skills/productivity"; RUNTIME_DEST="$ROOT/{RUNTIME_INSTALL_DIR}"; '
        f'SKILLS_BACKUP="$ROOT/backups/brief-me-package-{stamp}"; RUNTIME_BACKUP="$ROOT/backups/brief-me-runtime-{stamp}"; '
        f'STAGE="$ROOT/.brief-me-package-stage-{stamp}-$$"; '
        'cleanup() { rm -rf "$STAGE"; }; trap cleanup EXIT; '
        'mkdir -p "$DEST" "$SKILLS_BACKUP" "$RUNTIME_BACKUP" "$STAGE"; tar -xf - -C "$STAGE"; '
        'test -f "$STAGE/runtime/task_runtime.py"; '
        f'for NAME in {skills}; do '
        'test -f "$STAGE/$NAME/SKILL.md"; '
        'if test -e "$DEST/$NAME"; then cp -a "$DEST/$NAME" "$SKILLS_BACKUP/$NAME"; fi; '
        'rm -rf "$DEST/$NAME"; mv "$STAGE/$NAME" "$DEST/$NAME"; '
        'done; '
        'if test -e "$RUNTIME_DEST"; then cp -a "$RUNTIME_DEST" "$RUNTIME_BACKUP/task-runtime"; fi; '
        'rm -rf "$RUNTIME_DEST"; mkdir -p "$RUNTIME_DEST"; cp "$STAGE/runtime/task_runtime.py" "$RUNTIME_DEST/task_runtime.py"; '
        f'printf "skills_installed=%s runtime_installed=true backup_created=true\\n" "{len(SKILLS)}"'
    )


def deploy_ssh(target: dict[str, Any], archive: bytes, timeout: int, dry_run: bool) -> dict[str, Any]:
    agent = str(target.get("agent", "remote"))
    ssh_target = str(target["ssh_target"])
    profile_root = str(target.get("profile_root") or "~/.hermes")
    mode = str(target.get("mode") or "posix")
    if dry_run:
        return {"agent": agent, "ok": True, "dry_run": True, "skills_installed": len(SKILLS), "runtime_installed": True}
    command = remote_install_command(profile_root, time.strftime("%Y%m%d-%H%M%S"))
    if mode == "wsl":
        one_line = command.replace("\n", "; ")
        escaped = one_line.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        remote_command = f'wsl.exe sh -lc "{escaped}"'
    elif mode == "posix":
        remote_command = command
    else:
        return {"agent": agent, "ok": False, "error": f"unsupported target mode: {mode}"}
    ssh_args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
    if target.get("ssh_port"):
        ssh_args.extend(["-p", str(target["ssh_port"])])
    proc = subprocess.run(
        ssh_args + [ssh_target, remote_command],
        input=archive,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return {"agent": agent, "ok": False, "error": (proc.stderr or proc.stdout).decode(errors="replace")[-400:] or f"ssh exit {proc.returncode}"}
    return {"agent": agent, "ok": True, "skills_installed": len(SKILLS), "runtime_installed": True, "backup_created": True}


def deploy_target(target: dict[str, Any], source: Path, runtime: Path, archive: bytes, timeout: int, dry_run: bool) -> dict[str, Any]:
    try:
        kind = str(target.get("type", "local"))
        if kind == "local":
            return deploy_local(target, source, runtime, dry_run)
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
    source, runtime = source_root(repo), runtime_source(repo)
    targets = load_targets(args.config)
    if args.agent:
        wanted = set(args.agent)
        targets = [target for target in targets if str(target.get("agent")) in wanted]
        if not targets:
            parser.error("no configured targets matched --agent")
    bundle = archive_bytes(source, runtime)
    results = [deploy_target(target, source, runtime, bundle, args.timeout, args.dry_run) for target in targets]
    output = {"repo_root": str(repo), "target_count": len(results), "all_ok": all(bool(item.get("ok")) for item in results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{item['agent']}: {'OK' if item['ok'] else 'ERROR'}" for item in results))
    return 0 if output["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
