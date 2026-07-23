#!/usr/bin/env python3
"""TDD coverage for public-release distribution safeguards."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_remote_command_reports_structured_rollback_and_never_ignores_restore_copy_failure(self) -> None:
        command = deploy.remote_install_command("~/.hermes", "20260101-010101")
        self.assertIn("rollback()", command)
        self.assertIn("apply_succeeded", command)
        self.assertIn("rollback_attempted", command)
        self.assertIn("rollback_succeeded", command)
        self.assertIn("rolled_back", command)
        self.assertIn("skills_backup", command)
        self.assertIn("runtime_backup", command)
        self.assertIn("preinstall_manifest", command)
        self.assertNotIn('cp -a "$SKILLS_BACKUP/$NAME" "$DEST/$NAME" || true', command)
        self.assertNotIn('cp -a "$RUNTIME_BACKUP/task-runtime" "$RUNTIME_DEST" || true', command)

    def test_readme_limits_transaction_and_rollback_claims_to_one_target(self) -> None:
        """Public operator documentation must not imply batch/global atomicity."""
        readme = (ROOT / "README.md").read_text()
        self.assertIn("### Per-target transactional boundary", readme)
        self.assertIn("transactional only within one target profile", readme)
        self.assertIn("no batch/global atomicity", readme)
        self.assertIn("does not undo a previously successful target", readme)
        self.assertIn("installation remains inactive", readme)

    def test_unparseable_remote_failure_is_unknown_not_claimed_rolled_back(self) -> None:
        failed = subprocess.CompletedProcess(args=["ssh"], returncode=1, stdout=b"", stderr=b"transport failed")
        with patch.object(deploy.subprocess, "run", return_value=failed):
            result = deploy.deploy_ssh(
                {"agent": "test", "ssh_target": "example.invalid", "profile_root": "~/.hermes"},
                b"archive", timeout=1, dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["apply_succeeded"])
        self.assertEqual(result["rollback_attempted"], "unknown")
        self.assertEqual(result["rollback_succeeded"], "unknown")
        self.assertFalse(result["rolled_back"])

    def test_remote_timeout_is_unknown_not_claimed_rolled_back(self) -> None:
        with patch.object(deploy.subprocess, "run", side_effect=subprocess.TimeoutExpired(["ssh"], 1)):
            result = deploy.deploy_ssh(
                {"agent": "test", "ssh_target": "example.invalid", "profile_root": "~/.hermes"},
                b"archive", timeout=1, dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["apply_succeeded"])
        self.assertEqual(result["rollback_attempted"], "unknown")
        self.assertEqual(result["rollback_succeeded"], "unknown")
        self.assertFalse(result["rolled_back"])

    def test_remote_failure_with_non_boolean_rollback_fields_is_unknown(self) -> None:
        malformed = subprocess.CompletedProcess(
            args=["ssh"], returncode=1,
            stdout=b'{"apply_succeeded": false, "rollback_attempted": "yes", "rollback_succeeded": true, "rolled_back": false}\n',
            stderr=b"remote failed",
        )
        with patch.object(deploy.subprocess, "run", return_value=malformed):
            result = deploy.deploy_ssh(
                {"agent": "test", "ssh_target": "example.invalid", "profile_root": "~/.hermes"},
                b"archive", timeout=1, dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["apply_succeeded"])
        self.assertEqual(result["rollback_attempted"], "unknown")
        self.assertEqual(result["rollback_succeeded"], "unknown")
        self.assertFalse(result["rolled_back"])

    def test_parseable_remote_apply_failure_preserves_all_confirmed_status_fields(self) -> None:
        reported = {
            "apply_succeeded": False,
            "rollback_attempted": True,
            "rollback_succeeded": True,
            "rolled_back": True,
        }
        failed = subprocess.CompletedProcess(
            args=["ssh"], returncode=1,
            stdout=(json.dumps(reported) + "\n").encode(), stderr=b"apply failed",
        )
        with patch.object(deploy.subprocess, "run", return_value=failed):
            result = deploy.deploy_ssh(
                {"agent": "test", "ssh_target": "example.invalid", "profile_root": "~/.hermes"},
                b"archive", timeout=1, dry_run=False,
            )
        self.assertFalse(result["ok"])
        self.assertEqual({field: result[field] for field in reported}, reported)

    def test_remote_script_emits_parseable_outcomes_for_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "profile"
            source, runtime = self.source()
            command = deploy.remote_install_command(str(root), "20260101-010101")
            success = subprocess.run(["sh", "-c", command], input=deploy.archive_bytes(source, runtime), capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            successful_result = json.loads(success.stdout.decode().splitlines()[-1])
            self.assertTrue(successful_result["apply_succeeded"])
            self.assertFalse(successful_result["rollback_attempted"])
            self.assertFalse(successful_result["rollback_succeeded"])
            self.assertFalse(successful_result["rolled_back"])
            self.assertTrue((root / "runtime" / "task-runtime" / "task_runtime.py").is_file())

            failure = subprocess.run(["sh", "-c", command], input=b"not a tar archive", capture_output=True)
            self.assertNotEqual(failure.returncode, 0)
            failed_result = json.loads(failure.stdout.decode().splitlines()[-1])
            self.assertFalse(failed_result["apply_succeeded"])
            self.assertTrue(failed_result["rollback_attempted"])
            self.assertTrue(failed_result["rollback_succeeded"])
            self.assertFalse(failed_result["rolled_back"])

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

    def test_preflight_covers_release_credential_categories_without_echoing_values(self) -> None:
        samples = {
            "aws_access_key_id": b"AK" + b"IA" + (b"A" * 16),
            "azure_sas": b"sv=" + b"2024-01-01" + b"&" + b"sig=" + (b"a" * 32),
            "credential_url": b"postgres" + b"://" + b"user" + b":" + b"password" + b"@" + b"example.invalid/db",
            "credential_assignment": b"api" + b"_key=" + (b"a" * 24),
            "email_address": b"person" + b"@" + b"private.example",
        }
        findings = preflight.scan_bytes(b"\n".join(samples.values()), "fixture")
        categories = {finding["category"] for finding in findings}
        self.assertTrue(set(samples).issubset(categories))
        serialized = json.dumps(findings)
        for value in samples.values():
            self.assertNotIn(value.decode(), serialized)

    def test_preflight_allows_only_generic_release_and_reserved_test_email_domains(self) -> None:
        generic = b"maintainer" + b"@" + b"users.noreply.github.com"
        reserved_test = b"person" + b"@" + b"example.invalid"
        rfc_example = b"example" + b"@" + b"example.com"
        private = b"person" + b"@" + b"private.example"
        generic_findings = preflight.scan_bytes(generic, "generic")
        test_findings = preflight.scan_bytes(reserved_test, "test")
        example_findings = preflight.scan_bytes(rfc_example, "rfc-example")
        private_findings = preflight.scan_bytes(private, "private")
        self.assertNotIn("email_address", {finding["category"] for finding in generic_findings})
        self.assertNotIn("email_address", {finding["category"] for finding in test_findings})
        self.assertNotIn("email_address", {finding["category"] for finding in example_findings})
        self.assertIn("email_address", {finding["category"] for finding in private_findings})
        self.assertNotIn(private.decode(), json.dumps(private_findings))

    def test_preflight_scans_candidate_archive_and_public_probe_without_echoing_values(self) -> None:
        archive_token = b"ghp_" + (b"a" * 36)
        public_token = b"sk-" + (b"b" * 24)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "candidate.tar"
            with tarfile.open(archive, "w") as output:
                info = tarfile.TarInfo("payload.txt")
                info.size = len(archive_token)
                output.addfile(info, io.BytesIO(archive_token))
            archive_findings = preflight.candidate_archive(archive, [])

        class FakeResponse:
            status = 200

            def geturl(self) -> str:
                return "https://raw.githubusercontent.com/owner/repo/main/raw"

            def read(self, size: int = -1) -> bytes:
                return public_token

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(preflight, "open_public_url", return_value=FakeResponse()):
            probe_findings = preflight.public_probe("https://raw.githubusercontent.com/owner/repo/main/raw", [], 0)

        findings = archive_findings + probe_findings
        categories = {item["category"] for item in findings}
        self.assertIn("github_token", categories)
        self.assertIn("generic_api_key", categories)
        serialized = json.dumps(findings)
        self.assertNotIn(archive_token.decode(), serialized)
        self.assertNotIn(public_token.decode(), serialized)
        self.assertNotIn("example.invalid", serialized)

    def test_preflight_cli_fails_closed_across_all_surfaces_without_echoing_matches(self) -> None:
        """One deterministic CLI run must cover every release-scan surface."""
        tracked_token = b"ghp_" + (b"t" * 36)
        staged_token = b"sk-" + (b"s" * 24)
        historical_token = b"ghp_" + (b"h" * 36)
        archive_token = b"sk-" + (b"a" * 24)
        probe_token = b"ghp_" + (b"p" * 36)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"
            repo.mkdir()
            (repo / "tracked.txt").write_bytes(tracked_token)
            (repo / "history.txt").write_bytes(historical_token)
            (repo / "staged.txt").write_text("clean")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            noreply = "maintainer" + "@" + "users.noreply.invalid"
            identity = ["-c", "user.name=Project Maintainer", "-c", "user.email=" + noreply]
            subprocess.run(["git", *identity, "commit", "-qm", "fixture"], cwd=repo, check=True)
            (repo / "history.txt").unlink()
            (repo / "staged.txt").write_bytes(staged_token)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            archive = Path(directory) / "candidate.tar"
            with tarfile.open(archive, "w") as output:
                member = tarfile.TarInfo("release.txt")
                member.size = len(archive_token)
                output.addfile(member, io.BytesIO(archive_token))
            deny_terms = Path(directory) / "deny-terms.txt"
            deny_terms.write_text("generic-private-term-not-present\n")

            class FakeResponse:
                status = 200

                def geturl(self) -> str:
                    return "https://raw.githubusercontent.com/owner/repo/main/release"

                def read(self, size: int = -1) -> bytes:
                    return probe_token

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            output = io.StringIO()
            arguments = [
                "public_release_preflight.py", "--repo-root", str(repo),
                "--deny-terms-file", str(deny_terms), "--candidate-archive", str(archive),
                "--public-probe-url", "https://raw.githubusercontent.com/owner/repo/main/release", "--json",
            ]
            with patch.object(sys, "argv", arguments), patch.object(preflight, "open_public_url", return_value=FakeResponse()), redirect_stdout(output):
                exit_code = preflight.main()

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        references = {finding["reference"] for finding in result["findings"]}
        self.assertTrue(any(reference.startswith("tracked:") for reference in references))
        self.assertIn("staged_diff", references)
        self.assertTrue(any(reference.startswith("history_blob:") for reference in references))
        self.assertTrue(any(reference.startswith("candidate_archive:") for reference in references))
        self.assertIn("public_probe:0", references)
        serialized = json.dumps(result)
        for value in (tracked_token, staged_token, historical_token, archive_token, probe_token):
            self.assertNotIn(value.decode(), serialized)
        self.assertNotIn("example.invalid", serialized)

    def test_preflight_fails_closed_on_public_probe_transport_failure(self) -> None:
        with patch.object(preflight, "open_public_url", side_effect=OSError("network unavailable")):
            findings = preflight.public_probe("https://raw.githubusercontent.com/owner/repo/main/raw", [], 0)
        self.assertEqual(findings, [{"category": "public_probe_fetch_error", "reference": "public_probe:0"}])

    def test_preflight_rejects_private_numeric_probe_without_fetch(self) -> None:
        loopback_url = "https://" + ".".join(("127", "0", "0", "1")) + "/raw"
        with patch.object(preflight, "open_public_url") as fetch:
            findings = preflight.public_probe(loopback_url, [], 0)
        self.assertEqual(findings, [{"category": "invalid_public_probe_url", "reference": "public_probe:0"}])
        fetch.assert_not_called()

    def test_preflight_rejects_localhost_probe_without_fetch(self) -> None:
        """A hostname must not turn a public-release probe into a local request."""
        with patch.object(preflight, "open_public_url") as fetch:
            findings = preflight.public_probe("https://localhost/raw", [], 0)
        self.assertEqual(findings, [{"category": "invalid_public_probe_url", "reference": "public_probe:0"}])
        fetch.assert_not_called()

    def test_preflight_rejects_nonofficial_and_unsupported_official_probe_without_fetch(self) -> None:
        """Only the documented GitHub raw/API path shapes may reach the fetch wrapper."""
        invalid_urls = (
            "https://example.com/owner/repo/main/file",
            "https://api.github.com/user",
            "https://raw.githubusercontent.com/owner/repo/main",
        )
        with patch.object(preflight, "open_public_url") as fetch:
            for url in invalid_urls:
                with self.subTest(url=url):
                    findings = preflight.public_probe(url, [], 0)
                    self.assertEqual(findings, [{"category": "invalid_public_probe_url", "reference": "public_probe:0"}])
        fetch.assert_not_called()

    def test_preflight_accepts_only_supported_official_probe_url_patterns(self) -> None:
        self.assertTrue(preflight.valid_public_probe_url("https://raw.githubusercontent.com/owner/repo/v0.1.1/file.txt"))
        self.assertTrue(preflight.valid_public_probe_url("https://api.github.com/repos/owner/repo/contents/file.txt?ref=v0.1.1"))
        self.assertFalse(preflight.valid_public_probe_url("https://api.github.com/user"))
        self.assertFalse(preflight.valid_public_probe_url("https://raw.githubusercontent.com/owner/repo/main"))

    def test_preflight_rejects_unsafe_redirect_before_following(self) -> None:
        request = preflight.Request("https://raw.githubusercontent.com/owner/repo/main/raw")
        handler = preflight.PublicProbeRedirectHandler()
        with self.assertRaises(preflight.UnsafeProbeRedirect):
            handler.redirect_request(request, None, 302, "Found", {}, "https://localhost/private")

    def test_preflight_rejects_redirect_to_private_endpoint(self) -> None:
        class RedirectedResponse:
            status = 200

            def geturl(self) -> str:
                return "https://" + ".".join(("127", "0", "0", "1")) + "/private"

            def read(self, size: int = -1) -> bytes:
                return b"generic public payload"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(preflight, "open_public_url", return_value=RedirectedResponse()):
            findings = preflight.public_probe("https://raw.githubusercontent.com/owner/repo/main/raw", [], 0)
        self.assertEqual(findings, [{"category": "invalid_public_probe_redirect", "reference": "public_probe:0"}])

    def make_git_repo_with_untracked_file(self, path: Path) -> tuple[str, str]:
        """Create a repo where one tracked file is missing from the manifest allow-list."""
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        (path / "listed.txt").write_text("listed")
        (path / "unlisted.txt").write_text("unlisted")
        (path / "release-manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "version": "v0.1.0",
            "files": {"listed.txt": puller.sha256(path / "listed.txt")},
        }, indent=2))
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        identity = ["-c", "user.name=Project Maintainer", "-c", "user.email=" + ("maintainer" + "@" + "users.noreply.invalid")]
        subprocess.run(["git", "-C", str(path), *identity, "commit", "-qm", "release"], check=True)
        commit = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
        subprocess.run(["git", "-C", str(path), "tag", "v0.1.0"], check=True)
        manifest_blob = subprocess.run(["git", "-C", str(path), "hash-object", "release-manifest.json"], text=True, capture_output=True, check=True).stdout.strip()
        return commit, manifest_blob

    def test_manifest_is_git_tree_bound_and_rejects_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"; repo.mkdir()
            commit, manifest_blob = self.make_git_repo_with_untracked_file(repo)
            checkout = Path(directory) / "checkout"
            with self.assertRaises(puller.PullError) as ctx:
                puller.pull_release(str(repo), "v0.1.0", commit, checkout, dry_run=False)
            self.assertIn("not listed in the release manifest allow-list", str(ctx.exception))

    def test_manifest_blob_mismatch_rejects_pull(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"; repo.mkdir(); commit = self.make_git_repo(repo)
            checkout = Path(directory) / "checkout"
            result = puller.pull_release(str(repo), "v0.1.0", commit, checkout, dry_run=False)
            self.assertTrue(result["ok"])
            # Tamper with the manifest in the checkout after a successful pull.
            (checkout / "release-manifest.json").write_text(json.dumps({"schema_version": 1, "version": "v0.1.0", "files": {"payload.txt": "deadbeef" * 8}}, indent=2))
            with self.assertRaises(puller.PullError) as ctx:
                puller.verify_manifest(checkout, "v0.1.0")
            self.assertIn("does not match the committed Git tree blob", str(ctx.exception))

    def test_complete_manifest_allow_list_passes_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "source"; repo.mkdir(); commit = self.make_git_repo(repo)
            checkout = Path(directory) / "checkout"
            result = puller.pull_release(str(repo), "v0.1.0", commit, checkout, dry_run=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["manifest"]["file_count"], 1)
            self.assertTrue((checkout / "payload.txt").is_file())

    def test_corrective_release_manifest_is_complete_for_v011(self) -> None:
        """The next public tag must verify its entire committed payload, not v0.1.0 hashes."""
        manifest = json.loads((ROOT / "release-manifest.json").read_text())
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["version"], "v0.1.1")
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.splitlines()
        expected = {relative for relative in tracked if relative != "release-manifest.json"}
        self.assertEqual(set(manifest["files"]), expected)
        for relative, digest in manifest["files"].items():
            self.assertEqual(digest, puller.sha256(ROOT / relative), relative)


if __name__ == "__main__":
    unittest.main()
