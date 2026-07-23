#!/usr/bin/env python3
"""Install the brief-me package and Task Runtime with backup-aware rollback.

Targets are supplied only through a private JSON config outside this repository.
`--dry-run` reports the planned operation and never writes a target. This tool does
not activate a runtime, create a schedule, or send external actions.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
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


class DeploymentError(RuntimeError):
    """A failed deployment that includes the exact rollback evidence paths."""

    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


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


def backup_name(prefix: str, stamp: str | None = None) -> str:
    return f"{prefix}-{stamp or time.strftime('%Y%m%d-%H%M%S')}"


def expand_local(path_text: str) -> Path:
    return Path(path_text).expanduser()


def preinstall_manifest(root: Path) -> dict[str, Any]:
    skills = {name: sha256(root / "skills" / "productivity" / name / "SKILL.md") for name in SKILLS}
    runtime = sha256(root / RUNTIME_INSTALL_DIR / "task_runtime.py")
    return {"skills": skills, "runtime": runtime}


def restore_local(skills_destination: Path, runtime_destination: Path, skills_backup: Path, runtime_backup: Path) -> None:
    """Restore exactly the skill/runtime paths touched by one local invocation."""
    for name in SKILLS:
        destination = skills_destination / name
        shutil.rmtree(destination, ignore_errors=True)
        previous = skills_backup / name
        if previous.exists():
            shutil.copytree(previous, destination, symlinks=True)
    shutil.rmtree(runtime_destination, ignore_errors=True)
    previous_runtime = runtime_backup / "task-runtime"
    if previous_runtime.exists():
        shutil.copytree(previous_runtime, runtime_destination, symlinks=True)


def deploy_local(target: dict[str, Any], source: Path, runtime: Path, dry_run: bool) -> dict[str, Any]:
    agent = str(target.get("agent", "local"))
    root = expand_local(str(target.get("profile_root", "~/.hermes")))
    skills_destination = root / "skills" / "productivity"
    runtime_destination = root / RUNTIME_INSTALL_DIR
    stamp = time.strftime("%Y%m%d-%H%M%S")
    skills_backup = root / "backups" / backup_name("brief-me-package", stamp)
    runtime_backup = root / "backups" / backup_name("brief-me-runtime", stamp)
    manifest = preinstall_manifest(root)
    result: dict[str, Any] = {
        "agent": agent,
        "skills_backup": str(skills_backup),
        "runtime_backup": str(runtime_backup),
        "preinstall_manifest": manifest,
        "skills_installed": len(SKILLS),
        "runtime_installed": True,
    }
    if dry_run:
        return {**result, "ok": True, "dry_run": True}
    try:
        skills_destination.mkdir(parents=True, exist_ok=True)
        skills_backup.mkdir(parents=True, exist_ok=False)
        runtime_backup.mkdir(parents=True, exist_ok=False)
        for name in SKILLS:
            existing = skills_destination / name
            if existing.exists():
                shutil.copytree(existing, skills_backup / name, symlinks=True)
        if runtime_destination.exists():
            shutil.copytree(runtime_destination, runtime_backup / "task-runtime", symlinks=True)
        for name in SKILLS:
            existing = skills_destination / name
            shutil.rmtree(existing, ignore_errors=True)
            shutil.copytree(source / name, existing, symlinks=True)
        shutil.rmtree(runtime_destination, ignore_errors=True)
        runtime_destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime, runtime_destination / "task_runtime.py")
        return {**result, "ok": True, "backup_created": True, "rolled_back": False}
    except Exception as exc:
        try:
            restore_local(skills_destination, runtime_destination, skills_backup, runtime_backup)
            rolled_back = True
        except Exception as restore_exc:
            raise DeploymentError(f"deployment failed and rollback failed: {type(exc).__name__}: {exc}; {type(restore_exc).__name__}: {restore_exc}", {**result, "ok": False, "rolled_back": False}) from restore_exc
        raise DeploymentError(f"deployment failed and prior state was restored: {type(exc).__name__}: {exc}", {**result, "ok": False, "rolled_back": rolled_back}) from exc


def remote_root_expr(profile_root: str) -> str:
    if profile_root == "~":
        return "$HOME"
    if profile_root.startswith("~/"):
        return "$HOME/" + profile_root[2:]
    return profile_root


def _remote_manifest_program() -> str:
    code = """import hashlib,json,sys
from pathlib import Path
root,output=sys.argv[1:]
root=Path(root)
skills=['brief-me','build-me','ship-me','maintain-me']
def digest(path):
 try:return hashlib.sha256(path.read_bytes()).hexdigest()
 except OSError:return None
payload={'skills':{name:digest(root/'skills'/'productivity'/name/'SKILL.md') for name in skills},'runtime':digest(root/'runtime'/'task-runtime'/'task_runtime.py')}
Path(output).write_text(json.dumps(payload,sort_keys=True)+'\\n')
"""
    encoded = base64.b64encode(code.encode()).decode()
    return f"python3 -c \"import base64;exec(base64.b64decode('{encoded}'))\""


def remote_install_command(profile_root: str, stamp: str) -> str:
    root = remote_root_expr(profile_root)
    skills = " ".join(SKILLS)
    manifest_program = _remote_manifest_program()
    return (
        f'set -u; ROOT="{root}"; DEST="$ROOT/skills/productivity"; RUNTIME_DEST="$ROOT/{RUNTIME_INSTALL_DIR}"; '
        f'SKILLS_BACKUP="$ROOT/backups/brief-me-package-{stamp}"; RUNTIME_BACKUP="$ROOT/backups/brief-me-runtime-{stamp}"; '
        f'MANIFEST="$ROOT/backups/brief-me-preinstall-{stamp}.json"; STAGE="$ROOT/.brief-me-package-stage-{stamp}-$$"; CHANGED=0; APPLY_SUCCEEDED=false; ROLLBACK_ATTEMPTED=false; ROLLBACK_SUCCEEDED=false; ROLLED_BACK=false; '
        'cleanup() { rm -rf "$STAGE"; }; '
        'emit_result() { printf "{\\\"apply_succeeded\\\":%s,\\\"rollback_attempted\\\":%s,\\\"rollback_succeeded\\\":%s,\\\"rolled_back\\\":%s,\\\"skills_backup\\\":\\\"%s\\\",\\\"runtime_backup\\\":\\\"%s\\\",\\\"preinstall_manifest\\\":\\\"%s\\\",\\\"skills_installed\\\":4,\\\"runtime_installed\\\":true,\\\"backup_created\\\":true}\\n" "$APPLY_SUCCEEDED" "$ROLLBACK_ATTEMPTED" "$ROLLBACK_SUCCEEDED" "$ROLLED_BACK" "$SKILLS_BACKUP" "$RUNTIME_BACKUP" "$MANIFEST"; }; '
        'rollback() { rc="$1"; ROLLBACK_ATTEMPTED=true; ROLLBACK_SUCCEEDED=true; if test "$CHANGED" = 1; then '
        f'for NAME in {skills}; do rm -rf "$DEST/$NAME" || ROLLBACK_SUCCEEDED=false; if test -e "$SKILLS_BACKUP/$NAME"; then cp -a "$SKILLS_BACKUP/$NAME" "$DEST/$NAME" || ROLLBACK_SUCCEEDED=false; fi; done; '
        'rm -rf "$RUNTIME_DEST" || ROLLBACK_SUCCEEDED=false; if test -e "$RUNTIME_BACKUP/task-runtime"; then cp -a "$RUNTIME_BACKUP/task-runtime" "$RUNTIME_DEST" || ROLLBACK_SUCCEEDED=false; fi; if test "$ROLLBACK_SUCCEEDED" = true; then ROLLED_BACK=true; fi; fi; cleanup; emit_result; exit "$rc"; }; '
        'apply() { '
        'mkdir -p "$DEST" "$SKILLS_BACKUP" "$RUNTIME_BACKUP" "$STAGE" || return 1; '
        f'{manifest_program} "$ROOT" "$MANIFEST" || return 1; '
        'tar -xf - -C "$STAGE" || return 1; test -f "$STAGE/runtime/task_runtime.py" || return 1; '
        f'for NAME in {skills}; do test -f "$STAGE/$NAME/SKILL.md" || return 1; if test -e "$DEST/$NAME"; then cp -a "$DEST/$NAME" "$SKILLS_BACKUP/$NAME" || return 1; fi; done; '
        'if test -e "$RUNTIME_DEST"; then cp -a "$RUNTIME_DEST" "$RUNTIME_BACKUP/task-runtime" || return 1; fi; CHANGED=1; '
        f'for NAME in {skills}; do rm -rf "$DEST/$NAME" || return 1; mv "$STAGE/$NAME" "$DEST/$NAME" || return 1; done; '
        'rm -rf "$RUNTIME_DEST" || return 1; mkdir -p "$RUNTIME_DEST" || return 1; cp "$STAGE/runtime/task_runtime.py" "$RUNTIME_DEST/task_runtime.py" || return 1; }; '
        'if apply; then APPLY_SUCCEEDED=true; cleanup; emit_result; exit 0; else rollback 1; fi; '
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
        escaped = command.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        remote_command = f'wsl.exe sh -lc "{escaped}"'
    elif mode == "posix":
        remote_command = command
    else:
        return {"agent": agent, "ok": False, "error": f"unsupported target mode: {mode}"}
    ssh_args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
    if target.get("ssh_port"):
        ssh_args.extend(["-p", str(target["ssh_port"])])
    unknown_rollback = {
        "apply_succeeded": False,
        "rollback_attempted": "unknown",
        "rollback_succeeded": "unknown",
        "rolled_back": False,
    }
    try:
        proc = subprocess.run(ssh_args + [ssh_target, remote_command], input=archive, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {
            "agent": agent,
            "ok": False,
            **unknown_rollback,
            "error": "remote installer timed out without parseable rollback evidence",
        }
    text = proc.stdout.decode(errors="replace").strip().splitlines()
    try:
        payload = json.loads(text[-1])
    except (IndexError, json.JSONDecodeError):
        return {
            "agent": agent,
            "ok": False,
            **unknown_rollback,
            "error": "remote installer returned no parseable rollback evidence",
        }
    required = {"apply_succeeded", "rollback_attempted", "rollback_succeeded", "rolled_back"}
    if (
        not isinstance(payload, dict)
        or not required.issubset(payload)
        or any(type(payload[field]) is not bool for field in required)
    ):
        return {
            "agent": agent,
            "ok": False,
            **unknown_rollback,
            "error": "remote installer returned incomplete rollback evidence",
        }
    if proc.returncode != 0:
        return {
            "agent": agent,
            **payload,
            "ok": False,
            "error": (proc.stderr or proc.stdout).decode(errors="replace")[-500:] or f"ssh exit {proc.returncode}",
        }
    if payload["apply_succeeded"] is not True:
        return {"agent": agent, **payload, "ok": False, "error": "remote installer reported failed apply"}
    return {"agent": agent, **payload, "ok": True}


def deploy_target(target: dict[str, Any], source: Path, runtime: Path, archive: bytes, timeout: int, dry_run: bool) -> dict[str, Any]:
    try:
        kind = str(target.get("type", "local"))
        if kind == "local":
            return deploy_local(target, source, runtime, dry_run)
        if kind == "ssh":
            return deploy_ssh(target, archive, timeout, dry_run)
        return {"agent": str(target.get("agent", "unknown")), "ok": False, "error": f"unsupported target type: {kind}"}
    except DeploymentError as exc:
        return {"agent": str(target.get("agent", "unknown")), **exc.result, "error": str(exc)}
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
    repo = Path(args.repo_root).expanduser(); source = source_root(repo); runtime = runtime_source(repo)
    targets = load_targets(args.config)
    if args.agent:
        wanted = set(args.agent); targets = [target for target in targets if str(target.get("agent")) in wanted]
        if not targets:
            parser.error("no configured targets matched --agent")
    bundle = archive_bytes(source, runtime)
    results = [deploy_target(target, source, runtime, bundle, args.timeout, args.dry_run) for target in targets]
    output = {"repo_root": str(repo), "target_count": len(results), "all_ok": all(bool(item.get("ok")) for item in results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{item['agent']}: {'OK' if item['ok'] else 'ERROR'}" for item in results))
    return 0 if output["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
