---
name: maintain-me
description: Use after ship-me to monitor workflows, automations, apps/tools, and integrations; create quiet watchdogs, verify health, and auto-fix simple failures when safe.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [maintenance, monitoring, watchdogs, auto-fix, reliability, homelab]
    related_skills: [brief-me, build-me, ship-me, recurring-reports-and-personal-admin, automation-platform-operations]
---

# Maintain Me

## Overview

Use this skill after `ship-me` has made a workflow, app/tool, automation, or integration live. `maintain-me` keeps it healthy without creating noise.

Default: `maintain-me` may create quiet watchdogs and may auto-fix simple failures when safe.

Core principle:

```text
Healthy systems stay quiet. Broken systems alert with evidence, suggested action, and safe auto-fixes when allowed.
```

## When to Use

Use when:

- a newly shipped workflow/app needs monitoring;
- creating cron/watchdog checks;
- checking n8n workflow health and recent executions;
- monitoring container/service/URL health;
- validating backups, schedules, credentials expiry, or tunnel availability;
- implementing simple automatic recovery;
- turning repeated manual checks into quiet maintenance.

Do not use to design a new project; use `brief-me`. Do not use to build the initial version; use `build-me`. Do not use to activate/expose; use `ship-me`.

## Maintenance Policy

### Quiet by default

- Send nothing when healthy unless the user explicitly wants a digest.
- Alert only on failure, degradation, expiry, or repeated unusual state.
- Include evidence: command output, execution ID, status code, timestamp, affected workflow/service.
- Suggest the next action.

### Auto-fix simple failures when safe

Allowed examples:

- restart a non-critical failed container/service when the rollback is obvious;
- re-run a failed internal workflow once if idempotency is known;
- refresh a local cache;
- recreate a local tunnel process when documented;
- clear a stale lock file only when ownership and age are verified;
- disable a noisy watchdog if it is malfunctioning and notify the user.

Require approval before:

- destructive cleanup;
- broad database changes;
- workflow rewrites;
- DNS/tunnel/public-route changes;
- secret rotation/movement;
- repeated restarts of critical services;
- any auto-fix that can spam, lose data, or hide a serious outage.

## The Maintain-Me Loop

### 1. Define the Health Contract

For each shipped thing, document:

- what healthy means;
- how to check it;
- how often to check;
- what counts as degraded;
- what is safe to auto-fix;
- where to alert;
- how to disable the monitor.

### 2. Create a Quiet Watchdog

Good watchdogs:

- emit no output when healthy;
- emit a concise alert when broken;
- include evidence and timestamps;
- avoid secret-bearing diagnostics;
- have rate limiting or dedupe;
- do not recursively schedule more jobs;
- have a clear owner and disable path.

For Hermes cron jobs, prefer script-only `no_agent=True` when the script can produce the exact alert text and remain silent when healthy. Use an LLM-driven cron only when reasoning/summarization is needed.

### 3. Verify the Watchdog

Before trusting it:

- run the check manually;
- confirm healthy path is silent if designed that way;
- simulate or safely force a failure if possible;
- verify alert destination;
- document job ID/name and disable command.

### 4. Auto-Fix Safely

When a simple failure is detected:

1. collect evidence;
2. classify risk;
3. perform only the documented safe fix;
4. verify recovery;
5. alert with what happened if a fix was performed;
6. escalate if the fix fails or repeats.

### 5. Review Drift

Periodically check:

- workflows still active as intended;
- schedules still correct;
- credentials still valid;
- APIs still reachable;
- backups still recent;
- logs not accumulating repeated errors;
- costs/rate limits not surprising.

## Hermes Agent Task Watchdogs

For Hermes-agent work, use the durable task ledger watchdog rather than relying on the in-memory todo list. The hourly watchdog scans:

```bash
~/.hermes/scripts/agent_task_watchdog.py --stale-after-minutes 60
```

It may safely auto-resume only ledger tasks that explicitly set `safe_auto_resume=true`, have remaining attempts, and allow only safe actions such as `read_only_verify`, `retry_timeout`, `repo_validation`, `cron_validation`, `final_report`, or `recover_from_transcript`. It must alert instead of resuming when a task needs user approval, destructive changes, production mutation, real recipients, public posting, DNS/tunnel changes, secret handling, credential movement, or ambiguous next steps.

Every auto-resume attempt must be recorded:

```bash
~/.hermes/scripts/agent_task_ledger.py resume-event --task-id <task_id> --note "<why resume is safe>"
```

After recovery, update each acceptance check and run the final blocker before claiming completion.

## Mandatory MoE Stage Gate

Before closing a maintenance setup or handing it to ongoing operations, append a redacted `stage-gate/v1` maintenance record to the task’s canonical Google Doc:

```bash
python "${BRIEF_ME_PACKAGE_ROOT:-$HOME/brief-me}/scripts/moe_stage_gate.py" \
  --stage maintain-me \
  --artifact <redacted-maintain-record.json> \
  --doc-id <task-google-doc-id>
```

GPT-5.6 Sol checks the maintenance contract and escalation boundaries; DeepSeek V4 Pro checks the health evidence, alerting, dedupe, disable path, and bounded auto-fix policy. Both must pass. `NEEDS_REVISION` returns to the health contract/watchdog; `NEEDS_APPROVAL` pauses for the user; evaluator error blocks closure and is recorded in the Doc. Preserve the two reports independently; do not collapse them into a score.

## Health Contract Template

```markdown
# Maintain: <name>

**System:** <workflow/app/service>
**Owner/agent:** <who should react>
**Healthy means:** <observable healthy condition>
**Check method:** <command/API/query/execution inspection>
**Frequency:** <cron schedule>
**Healthy output:** Silent / digest / status line
**Alert destination:** <approved destination>
**Auto-fix allowed:** <exact safe fixes>
**Escalate when:** <failure repeats, critical condition, unsafe fix needed>
**Disable path:** <cron remove/pause, workflow disable, service stop>
**Secrets policy:** no secret values in logs/alerts
```

## n8n Maintenance Pattern

Monitor:

- active workflows expected to be active;
- last successful execution or staticData timestamp;
- repeated failures;
- workflows stuck or not finishing;
- schedule drift;
- destination misroutes;
- duplicate/spam signs;
- credentials metadata/expiry where available.

Be careful: successful scheduled n8n executions may not always be saved depending on workflow settings. Use workflow staticData or explicit heartbeat state when needed.

## App/Tool Maintenance Pattern

Monitor:

- container/service running;
- health endpoint status;
- logs for repeated errors;
- disk usage and volume mount availability;
- backups recent enough;
- TLS/cert expiry where relevant;
- tunnel/route reachability;
- restart loops or memory pressure.

Auto-fix can include a single restart for non-critical services, but repeated failure should escalate rather than loop forever.

## Alert Format

```markdown
# Maintenance Alert: <name>

**Status:** DEGRADED / FAILED / AUTO-FIXED / NEEDS APPROVAL
**Evidence:** <timestamp + concise command/API result>
**Impact:** <what is affected>
**Auto-fix attempted:** <yes/no and what happened>
**Next recommended action:** <specific>
**Disable path:** <if monitor itself is noisy>
```

## Common Pitfalls

1. **Noisy monitoring.** Healthy checks should usually be silent.
2. **Secret-bearing diagnostics.** Do not dump env/config/logs broadly.
3. **Auto-fix loops.** Try once or a small bounded number of times; escalate on repeat.
4. **Hiding outages.** Auto-fix should report what it did if something was actually broken.
5. **No disable path.** Every watchdog needs a way to stop it.
6. **Assuming n8n success logs exist.** Verify how the workflow records success.
7. **Monitoring too much too soon.** Start with the checks that prove the shipped promise.
8. **Changing production while maintaining.** Repairs beyond the documented safe fixes need approval.
9. **Pruning package siblings.** brief-me, build-me, ship-me, and maintain-me are a single integrated package. Do not install, remove, or update one without the others unless explicitly requested.
10. **Handoff gaps.** When you reach the boundary of one skill (e.g. brief is complete), explicitly invoke the next skill in the pipeline rather than continuing manually.

## Verification Checklist

- [ ] Health contract written.
- [ ] Watchdog is quiet when healthy or intentionally reports a digest.
- [ ] Failure alert includes evidence and no secrets.
- [ ] Alert destination is approved.
- [ ] Auto-fix scope is explicit and bounded.
- [ ] Manual run tested.
- [ ] Disable path documented.
- [ ] Escalation criteria defined.
- [ ] Maintenance handoff reported to the user.
