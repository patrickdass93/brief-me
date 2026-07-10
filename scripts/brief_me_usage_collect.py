#!/usr/bin/env python3
"""Collect compact, redacted evidence of brief-me package usage.

Designed for a Hermes cron job. It avoids broad env/config dumps and returns only
skill-related session snippets plus skill file hashes. Work/personal content
should be abstracted by the LLM before any skill edits are committed.

By default this inspects the local Hermes profile only. Add remote profiles with
`--remote-agent NAME=SSH_TARGET` or adapt REMOTE_SOURCES in a private copy.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TERMS = ["brief-me", "build-me", "ship-me", "maintain-me"]
EVIDENCE_PATTERNS = {
    "explicit_invocation": [r"\buse (?:the )?(brief-me|build-me|ship-me|maintain-me)\b", r"\bbrief me\b"],
    "user_correction": [r"\bcan we not\b", r"\binstead\b", r"\bnot do it that way\b", r"\bwrong\b", r"\bthat's not\b"],
    "approval_gate": [r"\bapproval\b", r"\bactivate\b", r"\bship\b", r"\bpublic\b", r"\breal recipient"],
    "verification_gap": [r"\bverify\b", r"\bverified\b", r"\bhash\b", r"\bdrift\b", r"\bmissing\b", r"\bfailed\b"],
    "handoff_confusion": [r"\bbuild-me\b.*\bship-me\b", r"\bbrief-me\b.*\bbuild-me\b", r"\bmaintain-me\b.*\bcron\b"],
}
REMOTE_SOURCES = []


def sanitize(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"https?://\S+", "[URL]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)
    text = re.sub(r"\b-?100\d{7,}\b", "[CHAT_ID]", text)
    text = re.sub(r"\b\d{10,}\b", "[LONG_NUMBER]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|authorization|password|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


COLLECTOR = r'''
import argparse, hashlib, json, re, sqlite3, time
from pathlib import Path
TERMS = ["brief-me", "build-me", "ship-me", "maintain-me"]
EVIDENCE_PATTERNS = {
    "explicit_invocation": [r"\buse (?:the )?(brief-me|build-me|ship-me|maintain-me)\b", r"\bbrief me\b"],
    "user_correction": [r"\bcan we not\b", r"\binstead\b", r"\bnot do it that way\b", r"\bwrong\b", r"\bthat's not\b"],
    "approval_gate": [r"\bapproval\b", r"\bactivate\b", r"\bship\b", r"\bpublic\b", r"\breal recipient"],
    "verification_gap": [r"\bverify\b", r"\bverified\b", r"\bhash\b", r"\bdrift\b", r"\bmissing\b", r"\bfailed\b"],
    "handoff_confusion": [r"\bbuild-me\b.*\bship-me\b", r"\bbrief-me\b.*\bbuild-me\b", r"\bmaintain-me\b.*\bcron\b"],
}

def sanitize(text):
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"https?://\S+", "[URL]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)
    text = re.sub(r"\b-?100\d{7,}\b", "[CHAT_ID]", text)
    text = re.sub(r"\b\d{10,}\b", "[LONG_NUMBER]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|authorization|password|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def term_snippet(text, radius=280):
    text = sanitize(text)
    low = text.lower()
    idxs = [low.find(t) for t in TERMS if low.find(t) >= 0]
    idx = min(idxs) if idxs else 0
    start = max(0, idx - radius)
    end = min(len(text), idx + radius)
    snip = text[start:end]
    if start > 0: snip = "…" + snip
    if end < len(text): snip = snip + "…"
    return snip

def evidence_tags(text):
    text = sanitize(text).lower()
    tags = []
    for tag, patterns in EVIDENCE_PATTERNS.items():
        if any(re.search(p, text, re.I) for p in patterns):
            tags.append(tag)
    return tags

def sha_file(path):
    try:
        data = Path(path).read_bytes()
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return None

def collect(agent, days, limit, profile_root=None, summary_only=False):
    home = Path.home()
    root = Path(profile_root).expanduser() if profile_root else home / ".hermes"
    out = {"agent": agent, "home": str(home), "profile_root": str(root), "days": days, "skills": {}, "hits": [], "summary": {}}
    base = root / "skills" / "productivity"
    for name in TERMS:
        p = base / name / "SKILL.md"
        out["skills"][name] = {"exists": p.exists(), "bytes": p.stat().st_size if p.exists() else 0, "sha16": sha_file(p)}
    db = root / "state.db"
    if not db.exists():
        out["error"] = "state.db not found"
        return out
    cutoff = time.time() - days * 86400
    like_clause = " OR ".join(["lower(coalesce(m.content,'') || ' ' || coalesce(m.tool_calls,'')) LIKE ?" for _ in TERMS])
    params = [cutoff] + [f"%{t}%" for t in TERMS]
    query = f"""
      SELECT m.id, m.session_id, m.role, m.content, m.tool_calls, m.timestamp,
             coalesce(s.title,''), coalesce(s.source,''), coalesce(s.model,'')
      FROM messages m LEFT JOIN sessions s ON s.id = m.session_id
      WHERE m.timestamp >= ?
        AND m.role IN ('user','assistant')
        AND ({like_clause})
      ORDER BY m.timestamp DESC
      LIMIT {int(limit)}
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(query, params).fetchall()
    except Exception as e:
        out["error"] = f"sqlite query failed: {type(e).__name__}: {e}"
        return out
    sessions = set()
    term_counts = {t: 0 for t in TERMS}
    evidence_tag_counts = {tag: 0 for tag in EVIDENCE_PATTERNS}
    for mid, sid, role, content, tool_calls, ts, title, source, model in rows:
        raw = (content or '') + ' ' + (tool_calls or '')
        blob = raw.lower()
        hits = [t for t in TERMS if t in blob]
        for h in hits:
            term_counts[h] += 1
        tags = evidence_tags(raw)
        for tag in tags:
            evidence_tag_counts[tag] += 1
        sessions.add(sid)
        if not summary_only:
            out["hits"].append({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)),
                "session_hash": hashlib.sha256(str(sid).encode()).hexdigest()[:10],
                "role": role,
                "source": sanitize(source)[:80],
                "title": sanitize(title)[:120],
                "model": sanitize(model)[:80],
                "terms": hits,
                "evidence_tags": tags,
                "snippet": term_snippet(raw),
            })
    out["summary"] = {"hit_count": len(rows), "session_count": len(sessions), "term_counts": term_counts, "evidence_tag_counts": evidence_tag_counts}
    return out

ap = argparse.ArgumentParser()
ap.add_argument('--agent', required=True)
ap.add_argument('--days', type=int, default=14)
ap.add_argument('--limit', type=int, default=40)
ap.add_argument('--profile-root')
ap.add_argument('--summary-only', action='store_true')
args = ap.parse_args()
print(json.dumps(collect(args.agent, args.days, args.limit, args.profile_root, args.summary_only), ensure_ascii=False, indent=2))
'''


def run_local(agent: str, days: int, limit: int, profile_root: str | None = None, summary_only: bool = False) -> dict[str, Any]:
    cmd = [sys.executable, "-c", COLLECTOR, "--agent", agent, "--days", str(days), "--limit", str(limit)]
    if profile_root:
        cmd.extend(["--profile-root", profile_root])
    if summary_only:
        cmd.append("--summary-only")
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if p.returncode != 0:
        return {"agent": agent, "error": p.stderr[-1000:] or f"exit {p.returncode}"}
    return json.loads(p.stdout)


def run_remote(agent: str, target: str, days: int, limit: int, profile_root: str | None = None, mode: str = "posix", summary_only: bool = False) -> dict[str, Any]:
    encoded = base64.b64encode(COLLECTOR.encode()).decode()
    py = f"import base64,sys; exec(base64.b64decode({encoded!r}))"
    parts = ["python3", "-c", py, "--agent", agent, "--days", str(days), "--limit", str(limit)]
    if profile_root:
        parts.extend(["--profile-root", profile_root])
    if summary_only:
        parts.append("--summary-only")
    posix_remote = shlex.join(parts)
    remote = "wsl.exe sh -lc " + shlex.quote(posix_remote) if mode == "wsl" else posix_remote
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", target, remote], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    if p.returncode != 0:
        return {"agent": agent, "target": sanitize(target), "error": (p.stderr or p.stdout)[-1200:] or f"exit {p.returncode}"}
    try:
        return json.loads(p.stdout)
    except Exception as e:
        return {"agent": agent, "target": sanitize(target), "error": f"json parse failed: {e}", "raw_tail": p.stdout[-1000:]}


def repo_status() -> dict[str, Any]:
    repo = Path.home() / "brief-me"
    out = {"path": str(repo), "exists": repo.exists()}
    if not repo.exists():
        return out
    cmds = {
        "head": ["git", "rev-parse", "--short", "HEAD"],
        "status": ["git", "status", "--short"],
        "remote": ["git", "remote", "get-url", "origin"],
    }
    for k, cmd in cmds.items():
        try:
            p = subprocess.run(cmd, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            out[k] = sanitize(p.stdout.strip() if p.returncode == 0 else p.stderr.strip())
        except Exception as e:
            out[k] = f"error: {type(e).__name__}: {e}"
    return out


def expected_manifest() -> dict[str, str]:
    repo_base = Path.home() / "brief-me" / "skills" / "productivity"
    local_base = Path.home() / ".hermes" / "skills" / "productivity"
    base = repo_base if repo_base.exists() else local_base
    return {name: (hashlib.sha256((base / name / "SKILL.md").read_bytes()).hexdigest()[:16] if (base / name / "SKILL.md").exists() else None) for name in TERMS}


def package_integrity(agents: list[dict[str, Any]], expected: dict[str, str]) -> dict[str, Any]:
    by_agent = {}
    all_ok = True
    for agent in agents:
        checks = {}
        for name in TERMS:
            info = agent.get("skills", {}).get(name, {})
            ok = bool(info.get("exists")) and info.get("sha16") == expected.get(name)
            checks[name] = ok
            all_ok = all_ok and ok
        by_agent[agent.get("agent", "unknown")] = checks
    return {"expected_sha16": expected, "all_agents_match_expected": all_ok, "by_agent": by_agent}


def decision_input(agents: list[dict[str, Any]], integrity: dict[str, Any]) -> dict[str, Any]:
    tag_totals = {tag: 0 for tag in EVIDENCE_PATTERNS}
    errors = []
    for agent in agents:
        if agent.get("error"):
            errors.append({"agent": agent.get("agent"), "error": agent.get("error")})
        for tag, count in agent.get("summary", {}).get("evidence_tag_counts", {}).items():
            tag_totals[tag] = tag_totals.get(tag, 0) + int(count or 0)
    return {
        "policy": "bounded_auto_commit",
        "default_decision": "no_change unless concrete reusable evidence exists",
        "auto_apply_allowed_for": [
            "small validated edits to package skill text",
            "generic pitfalls/verification gates derived from repeated evidence",
            "package drift reinstall when hashes/files do not match expected manifest",
        ],
        "proposal_required_for": [
            "ambiguous or one-off observations",
            "large rewrites or structural repo changes",
            "new side-effect policies, delivery changes, model/tool changes, or secret handling changes",
        ],
        "evidence_thresholds": {
            "edit": "at least one concrete failure/correction/misuse, or repeated weak signal across sessions/agents",
            "no_change": "usage observed but no reusable correction or failure pattern",
            "proposal": "plausible improvement with insufficient or ambiguous evidence",
            "drift_fix": "any missing package file or hash mismatch on an in-scope target",
        },
        "evidence_tag_totals": tag_totals,
        "collection_errors": errors,
        "package_integrity_ok": integrity.get("all_agents_match_expected"),
    }


def parse_remote_agent(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=SSH_TARGET")
    name, target = value.split("=", 1)
    if not name.strip() or not target.strip():
        raise argparse.ArgumentTypeError("agent name and SSH target must be non-empty")
    return name.strip(), target.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit-per-agent", type=int, default=40)
    ap.add_argument("--summary-only", action="store_true", help="Omit snippets; return counts, tags, and integrity metadata only.")
    ap.add_argument("--no-default-remotes", action="store_true", help="Only inspect the local profile and explicitly provided --remote-agent entries.")
    ap.add_argument("--local-agent-name", default="local")
    ap.add_argument("--remote-agent", action="append", type=parse_remote_agent, default=[], metavar="NAME=SSH_TARGET")
    args = ap.parse_args()

    agents = [run_local(args.local_agent_name, args.days, args.limit_per_agent, summary_only=args.summary_only)]
    sources = [] if args.no_default_remotes else list(REMOTE_SOURCES)
    sources.extend({"agent": a, "target": t} for a, t in args.remote_agent)
    for source in sources:
        agents.append(run_remote(source["agent"], source["target"], args.days, args.limit_per_agent, profile_root=source.get("profile_root"), mode=source.get("mode", "posix"), summary_only=args.summary_only))

    expected = expected_manifest()
    integrity = package_integrity(agents, expected)
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": "brief-me package usage review evidence; snippets are redacted and must be abstracted before committing skill improvements",
        "repo": repo_status(),
        "improvement_decision_input": decision_input(agents, integrity),
        "package_integrity": integrity,
        "agents": agents,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
