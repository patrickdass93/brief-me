#!/usr/bin/env python3
"""TDD coverage for public-release distribution safeguards."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


deploy = load("release_deploy", "deploy_package_install.py")
puller = load("pull_package_release", "pull_package_release.py")
preflight = load("public_release_preflight", "public_release_preflight.py")


class ReleaseDistributionTests(unittest.TestCase):
    def source(self) -> tuple[Path, Path]:
        return deploy.source_root(ROOT), deploy.runtime_source(ROOT)

    def test_local_install_reports_exact_backup_paths_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "hermes"
            old_skill = root / "skills" / "productivity" / "brief-me"
            old_skill.mkdir(parents=True)
            (old_skill / "SKILL.md").write_text("old-skill")
            old_runtime = root / "runtime" / "task-runtime"
            old_runtime.mkdir(parents=True)
            (old_runtime / "task_runtime.py").write_text("old-runtime")
            source, runtime = self.source()
            result = deploy.deploy_local({"agent": "test", "profile_root": str(root)}, source, runtime, dry_run=False)
            self.assertTrue(Path(result["skills_backup"]).is_dir())
            self.assertTrue(Path(result["runtime_backup"]).is_dir())
            self.assertEqual(len(result["preinstall_manifest"]["skills"]), 4)
            self.assertEqual((Path(result["skills_backup"]) / "brief-me" / "SKILL.md").read_text(), "old-skill")
            self.assertEqual((Path(result["runtime_backup"]) / "task-runtime" / "task_runtime.py").read_text(), "old-runtime")

    def test_local_failure_restores_prior_skill_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "hermes"
            old_skill = root / "skills" / "productivity" / "brief-me"
            old_skill.mkdir(parents=True)
            (old_skill / "SKILL.md").write_text("old-skill")
            old_runtime = root / "runtime" / "task-runtime"
            old_runtime.mkdir(parents=True)
            (old_runtime / "task_runtime.py").write_text("old-runtime")
            source, runtime = self.source()
            original_copy2 = deploy.shutil.copy2

            def fail_runtime_copy(src, dst, *args, **kwargs):
                if Path(dst).name == "task_runtime.py":
                    raise OSError("simulated runtime copy failure")
                return original_copy2(src, dst, *args, **kwargs)

            with patch.object(deploy.shutil, "copy2", side_effect=fail_runtime_copy):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.deploy_local({"agent": "test", "profile_root": str(root)}, source, runtime, dry_run=False)
            self.assertEqual((old_skill / "SKILL.md").read_text(), "old-skill")
            self.assertEqual((old_runtime / "task_runtime.py").read_text(), "old-runtime")

    def test_remote_command_contains_compensating_rollback_and_paths(self) -> None:
        command = deploy.remote_install_command("~/.hermes", "20260101-010101")
        self.assertIn("rollback()", command)
        self.assertIn("skills_backup", command)
        self.assertIn("runtime_backup", command)
        self.assertIn("preinstall_manifest", command)

    def make_git_repo(self, path: Path) -> str:
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        (path / "payload.txt").write_text("generic release")
        (path / "release-manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "version": "v0.1.0",
            "files": {"payload.txt": puller.sha256(path / "payload.txt")},
        }, indent=2))
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        identity = ["-c", "user.name=Project Maintainer", "-c", "user.email=" + ("maintainer" + "@" + "users.noreply.invalid")]
        subprocess.run(["git", "-C", str(path), *identity, "commit", "-qm", "release"], check=True)
        commit = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
        subprocess.run(["git", "-C", str(path), "tag", "v0.1.0"], check=True)
        return commit

    def test_pull_dry_run_does_not_create_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"; repo.mkdir(); commit = self.make_git_repo(repo)
            checkout = Path(directory) / "checkout"
            result = puller.pull_release(str(repo), "v0.1.0", commit, checkout, dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertFalse(checkout.exists())

    def test_pull_verifies_pinned_tag_and_does_not_install_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"; repo.mkdir(); commit = self.make_git_repo(repo)
            checkout = Path(directory) / "checkout"
            result = puller.pull_release(str(repo), "v0.1.0", commit, checkout, dry_run=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["commit"], commit)
            self.assertTrue((checkout / "release-manifest.json").is_file())
            self.assertFalse((checkout / "runtime" / "task-runtime").exists())

    def test_preflight_detects_token_pattern_without_echoing_value(self) -> None:
        token = b"ghp_" + (b"a" * 36)
        findings = preflight.scan_bytes(b"token=" + token, "fixture")
        self.assertTrue(findings)
        self.assertNotIn(token.decode(), json.dumps(findings))


if __name__ == "__main__":
    unittest.main()
