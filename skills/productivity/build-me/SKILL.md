---
name: build-me
description: Use after brief-me to execute the smallest safe build slice for workflows, automations, app/tool setups, and integrations using inspect-build-run-observe-fix loops.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [build-loop, n8n, automation, app-setup, verification, agent-loop]
    related_skills: [brief-me, ship-me, maintain-me, automation-platform-operations, linux-remote-system-operations]
---

# Build Me

## Overview

Use this skill after `brief-me` has produced a build brief. `build-me` executes the smallest safe slice, verifies it with real output, fixes failures, and repeats.

This is the non-coder/ops version of the coding-agent loop:

```text
Inspect → build one slice → run/test → observe → fix → verify → next slice
```

It is designed for n8n workflows, self-hosted app/tool setup, integrations, recurring automations, and agent workflows.

## When to Use

Use when:

- a `brief-me` brief exists or the task is already clearly scoped;
- the next action is low-risk enough to execute;
- building an inactive n8n workflow, local app config, sample-data test, or draft integration;
- debugging a build slice by inspecting execution output/logs;
- expanding from one verified slice to the next.

Do not use `build-me` to ship, activate, expose publicly, mutate production data broadly, or maintain a running system long-term. Use `ship-me` for release and `maintain-me` after release.

## Allowed Low-Risk Work

`build-me` can proceed automatically with:

- read-only inspection;
- creating draft files/configs with placeholders;
- creating inactive n8n workflows;
- testing with fake/sample data;
- local health checks;
- safe test sends to explicitly approved destinations;
- creating backups before modifying existing config/workflows;
- verifying logs, execution IDs, outputs, and health endpoints.

Pause and ask or hand to `ship-me` before:

- activating live workflows;
- public posting or real external recipient sends outside approved test destinations;
- deleting or overwriting resources;
- changing DNS/tunnels/public exposure;
- production migrations/backfills;
- moving/storing/printing secrets;
- restarting critical services.

## The Build-Me Loop

### 1. Load the Brief and Ledger

Start by summarizing:

- intent;
- first useful version;
- allowed actions;
- approval gates;
- verification command/output;
- rollback path;
- durable task ledger `task_id` if the task has 3+ steps, file/repo edits, cron/job changes, background processes, deployment, remote-host work, or explicit build/fix/verify requirements.

If no ledger exists for a multi-step task, create one before building:

```bash
~/.hermes/scripts/agent_task_ledger.py start \
  --title "<task title>" \
  --origin "<chat/session/source>" \
  --safe-auto-resume \
  --allowed-resume-actions "read_only_verify,retry_timeout,repo_validation,cron_validation,final_report,recover_from_transcript" \
  --check "slice1:<acceptance check>:<verification command/output>"
```

Update the ledger after every verified slice:

```bash
~/.hermes/scripts/agent_task_ledger.py progress --task-id <task_id> --check-id <slice> --check-status passed --evidence "<real output>"
```

If no brief exists, load `brief-me` first unless the task is obviously tiny.

### 2. Inspect Current State

Inspect before changing anything:

- n8n workflows, credentials metadata, recent executions;
- app host OS, Docker, ports, disk, services;
- existing files/configs;
- logs/errors;
- routes/tunnels/domains;
- database schema/row counts when relevant, without dumping sensitive data.

### 3. Build One Slice

Make the smallest change that can be verified:

- one n8n node chain;
- one webhook response;
- one local Docker Compose service;
- one sample transform;
- one dry-run branch;
- one health check.

Avoid broad rewrites and unrelated improvements.

### 4. Run or Simulate

Use the closest real test:

- manual n8n execution;
- test webhook payload;
- dry-run API call;
- `curl localhost`;
- container/service logs;
- database query for one known row;
- safe test message to approved destination.

### 5. Observe Before Fixing

If the run fails:

1. read the error/output;
2. identify the failing component;
3. make one targeted change;
4. rerun the same verification;
5. repeat.

Do not guess or stack multiple unverified fixes.

### 6. Record Evidence

For each completed slice, capture:

- command or execution ID;
- observed output/status;
- changed files/workflow ID/node names;
- side effects performed;
- unresolved risks.

### 7. Decide Next Skill

- More slices needed and still low-risk → continue `build-me`.
- Ready for activation/exposure/release → use `ship-me`.
- Already shipped and needs monitoring → use `maintain-me`.
- Scope unclear → return to `brief-me`.

## Final-Answer Ledger Gate

For any ledger-backed task, do not report “done” until all acceptance checks have passed, the task is closed, and the final blocker succeeds:

```bash
~/.hermes/scripts/agent_task_ledger.py close --task-id <task_id> --status completed
~/.hermes/scripts/agent_task_ledger.py check-final --task-id <task_id>
```

If the blocker fails, report the pending checks instead of claiming completion. Leave unsafe/approval-gated actions blocked in the ledger so the hourly watchdog alerts rather than auto-resumes.

## Mandatory MoE Stage Gate

Before handing a completed build to `ship-me`, create a redacted `stage-gate/v1` record with the build contract, changed resources, verification evidence, side effects, unresolved risks, and rollback. Reuse the task’s Google Doc ID from the brief/ledger:

```bash
python "${BRIEF_ME_PACKAGE_ROOT:-$HOME/brief-me}/scripts/moe_stage_gate.py" \
  --stage build-me \
  --artifact <redacted-build-record.json> \
  --doc-id <task-google-doc-id>
```

The gate calls **GPT-5.6 Sol** and **DeepSeek V4 Pro** in parallel and appends their separate reports to the canonical task Doc. `PASS` from both is required before `ship-me`. `NEEDS_REVISION` loops back to the smallest failing build slice (maximum three cycles); `NEEDS_APPROVAL` pauses for the user; evaluator error blocks the handoff until explicitly resolved. Never place secrets, raw credentials, or unredacted diagnostics in the record.

## n8n Build Pattern

1. Back up existing workflow JSON before modifying it.
2. Create new workflows inactive by default.
3. Start with Manual Trigger and sample payload.
4. Add transform/validation nodes before external actions.
5. Add dry-run outputs before real sends/writes.
6. Add idempotency before recurring activation.
7. Manually execute and inspect execution output.
8. Only proceed to `ship-me` when test executions match the brief.

Always verify workflow ID/name and active state after changes.

## App/Tool Setup Build Pattern

1. Inspect host reachability, OS, Docker/runtime, disk, memory, and ports.
2. Create minimal config with placeholders or approved env references.
3. Start locally only.
4. Verify container/service is running.
5. Run local health check.
6. Inspect logs for errors.
7. Verify persistence/restart if relevant.
8. Keep public exposure for `ship-me` unless explicitly low-risk/internal and pre-approved.

## Build Report Format

After each slice:

```markdown
## Build Slice Result: <name>

**Status:** PASS / FAIL / BLOCKED
**Changed:** <files/workflow/node/service>
**Verification run:** <command/execution ID/test payload>
**Observed output:** <concise real result>
**Side effects:** <none/test send/local write/etc>
**Next:** <continue/fix/ship/ask>
```

## Common Pitfalls

1. **Skipping the brief.** If the task has unclear side effects, go back to `brief-me`.
2. **Changing too much at once.** One slice at a time.
3. **Not verifying after edits.** File writes/API success are not enough; inspect output/logs/state.
4. **Using production data too early.** Use sample data first.
5. **Forgetting inactive-first n8n.** Do not activate live workflows during build.
6. **No backups before modifying existing workflows/config.** Export or copy first.
7. **Fail-open automations.** Missing or invalid data should stop quietly or log, not spam.
8. **Secret leakage.** Use names/metadata/env references only; never print secret values.

## Verification Checklist

- [ ] Brief or clear task exists.
- [ ] Current state inspected before changes.
- [ ] Only allowed low-risk actions were taken.
- [ ] One slice was built at a time.
- [ ] Real verification output was captured.
- [ ] Failures were diagnosed from output/logs.
- [ ] Idempotency was implemented before recurring/live use.
- [ ] Existing resources were backed up before modification.
- [ ] Side effects stayed within approved scope.
- [ ] Next skill decision is clear: build more, ship, maintain, or brief again.
