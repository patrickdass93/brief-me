#!/usr/bin/env python3
"""Fail-closed local privacy preflight for a candidate public Git release.

Scans tracked tree, staged diff, reachable history, the exact candidate archive,
and optional post-push public raw/API probes. It reports only category/ref/path
metadata, never the matching secret/term value or probe URL.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "generic_api_key": re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|rk_(?:live|test)_[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,})"),
    "aws_access_key_id": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "azure_sas": re.compile(rb"(?:^|[?&\r\n])sv=20\d{2}-\d{2}-\d{2}[^\r\n]*?(?:[?&]sig=[^&\s]{16,})"),
    "telegram_token": re.compile(rb"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    "credential_url": re.compile(rb"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis)://[^\s/@]+:[^\s/@]+@"),
    "credential_assignment": re.compile(rb"(?i)\b(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{20,}"),
    "ipv4_address": re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}
EMAIL_PATTERN = re.compile(rb"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
# These are non-routable test data, RFC 2606 example domains, and GitHub no-reply identities.
# All other email-shaped values remain a fail-closed public-release finding.
SAFE_PUBLIC_EMAIL_DOMAINS = frozenset({
    b"users.noreply.github.com", b"invalid", b"example.com", b"example.net", b"example.org",
})

MAX_PROBE_BYTES = 25 * 1024 * 1024
# Post-push probes deliberately support only the two official GitHub raw/API
# surfaces needed for this public distribution.  Do not accept arbitrary
# hostnames: a hostname can resolve to an internal address before urlopen sees
# a response, and permitting it would make a release probe an SSRF primitive.
SAFE_PUBLIC_PROBE_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})


def is_safe_public_email(match: bytes) -> bool:
    """Allow only GitHub no-reply and RFC-reserved `.invalid` test addresses."""
    _, _, domain = match.lower().rpartition(b"@")
    return domain in SAFE_PUBLIC_EMAIL_DOMAINS or domain.endswith(b".invalid")


def scan_bytes(data: bytes, reference: str, deny_terms: list[bytes] | None = None) -> list[dict[str, str]]:
    findings = [{"category": category, "reference": reference} for category, pattern in PATTERNS.items() if pattern.search(data)]
    if any(not is_safe_public_email(match.group(0)) for match in EMAIL_PATTERN.finditer(data)):
        findings.append({"category": "email_address", "reference": reference})
    for term in deny_terms or []:
        if term and term.lower() in data.lower():
            findings.append({"category": "deny_term", "reference": reference})
    return findings


def run(args: list[str], repo: Path) -> bytes:
    result = subprocess.run(args, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).decode(errors="replace").strip() or "git command failed")
    return result.stdout


def deny_terms(path: Path) -> list[bytes]:
    return [line.strip().encode() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def tracked_tree(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for raw in run(["git", "ls-files", "-z"], repo).split(b"\0"):
        if not raw:
            continue
        relative = raw.decode(errors="replace")
        try:
            findings.extend(scan_bytes((repo / relative).read_bytes(), f"tracked:{relative}", terms))
        except OSError:
            findings.append({"category": "unreadable_tracked_file", "reference": f"tracked:{relative}"})
    return findings


def staged_diff(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    return scan_bytes(run(["git", "diff", "--cached", "--binary"], repo), "staged_diff", terms)


def reachable_history(repo: Path, terms: list[bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    objects = run(["git", "rev-list", "--objects", "--all"], repo).splitlines()
    seen: set[bytes] = set()
    for item in objects:
        object_id = item.split(maxsplit=1)[0]
        if object_id in seen:
            continue
        seen.add(object_id)
        object_type = run(["git", "cat-file", "-t", object_id.decode()], repo).strip()
        if object_type != b"blob":
            continue
        findings.extend(scan_bytes(run(["git", "cat-file", "-p", object_id.decode()], repo), f"history_blob:{object_id.decode()[:12]}", terms))
    metadata = run(["git", "log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce"], repo)
    for row in metadata.splitlines():
        findings.extend(scan_bytes(row, "commit_identity", terms))
    return findings


def candidate_archive(archive: Path, terms: list[bytes]) -> list[dict[str, str]]:
    """Scan every regular member of the exact candidate archive, fail closed on errors."""
    findings: list[dict[str, str]] = []
    try:
        with tarfile.open(archive, "r:*") as candidate:
            for member in candidate:
                reference = f"candidate_archive:{member.name}"
                if member.isdir():
                    continue
                if not member.isfile() or member.size > MAX_PROBE_BYTES:
                    findings.append({"category": "unsupported_archive_member", "reference": reference})
                    continue
                payload = candidate.extractfile(member)
                if payload is None:
                    findings.append({"category": "unreadable_archive_member", "reference": reference})
                    continue
                findings.extend(scan_bytes(payload.read(), reference, terms))
    except (OSError, tarfile.TarError):
        return [{"category": "unreadable_candidate_archive", "reference": "candidate_archive"}]
    return findings


def supported_probe_path(parsed) -> bool:  # type: ignore[no-untyped-def]
    """Allow only explicit GitHub raw-content and contents-API resource shapes."""
    if parsed.fragment:
        return False
    parts = parsed.path.split("/")
    if not parts or parts[0] != "":
        return False
    parts = parts[1:]
    if not parts or any(not part or unquote(part) != part or part in {".", ".."} for part in parts):
        return False
    host = parsed.hostname.lower()
    if host == "raw.githubusercontent.com":
        # /<owner>/<repo>/<immutable-ref>/<file...>; query parameters are unsupported.
        return len(parts) >= 4 and not parsed.query
    if host == "api.github.com":
        # /repos/<owner>/<repo>/contents/<file...> with an optional exact ref.
        if len(parts) < 5 or parts[:1] != ["repos"] or parts[3:4] != ["contents"]:
            return False
        query = parse_qsl(parsed.query, keep_blank_values=True)
        return not query or (len(query) == 1 and query[0][0] == "ref" and bool(query[0][1]))
    return False


def valid_public_probe_url(url: str) -> bool:
    """Accept only explicit HTTPS GitHub raw-content/API resources without credentials."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or not parsed.hostname:
        return False
    try:
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return parsed.hostname.lower() in SAFE_PUBLIC_PROBE_HOSTS and supported_probe_path(parsed)
    return False


class UnsafeProbeRedirect(Exception):
    """Raised before urllib follows a redirect outside the probe allow-list."""


class PublicProbeRedirectHandler(HTTPRedirectHandler):
    """Fail closed before following an unsafe redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not valid_public_probe_url(newurl):
            raise UnsafeProbeRedirect()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_public_url(request: Request, timeout: int):
    """Open a probe with redirects constrained before a second request occurs."""
    return build_opener(PublicProbeRedirectHandler()).open(request, timeout=timeout)


def public_probe(url: str, terms: list[bytes], index: int) -> list[dict[str, str]]:
    """Fetch and scan public release content without echoing route or payload."""
    reference = f"public_probe:{index}"
    if not valid_public_probe_url(url):
        return [{"category": "invalid_public_probe_url", "reference": reference}]
    try:
        request = Request(url, headers={"User-Agent": "brief-me-release-preflight/1"})
        with open_public_url(request, timeout=20) as response:
            final_url = response.geturl()
            if not valid_public_probe_url(final_url):
                return [{"category": "invalid_public_probe_redirect", "reference": reference}]
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                return [{"category": "public_probe_http_status", "reference": reference}]
            payload = response.read(MAX_PROBE_BYTES + 1)
    except UnsafeProbeRedirect:
        return [{"category": "invalid_public_probe_redirect", "reference": reference}]
    except Exception:
        return [{"category": "public_probe_fetch_error", "reference": reference}]
    if len(payload) > MAX_PROBE_BYTES:
        return [{"category": "public_probe_too_large", "reference": reference}]
    return scan_bytes(payload, reference, terms)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--deny-terms-file", required=True)
    parser.add_argument("--candidate-archive", help="Exact release archive to scan before publishing")
    parser.add_argument("--public-probe-url", action="append", default=[], help="HTTPS raw/API URL to scan after publishing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo_root).expanduser().resolve()
    terms = deny_terms(Path(args.deny_terms_file).expanduser())
    findings = tracked_tree(repo, terms) + staged_diff(repo, terms) + reachable_history(repo, terms)
    if args.candidate_archive:
        findings.extend(candidate_archive(Path(args.candidate_archive).expanduser(), terms))
    for index, url in enumerate(args.public_probe_url):
        findings.extend(public_probe(url, terms, index))
    result = {"ok": not findings, "finding_count": len(findings), "findings": findings}
    print(json.dumps(result, indent=2) if args.json else f"public_release_preflight={'PASS' if result['ok'] else 'FAIL'} findings={len(findings)}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
