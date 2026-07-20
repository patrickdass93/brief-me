---
name: brief-me
description: Use when starting a workflow, automation, app/tool setup, integration, or agent project; grill the idea into a compact build brief, then hand off to build-me for low-risk first slices.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [briefing, grill-me, planning, n8n, automation, agent-loop]
    related_skills: [grill-me, build-me, ship-me, maintain-me, automation-platform-operations, writing-plans]
---

# Brief Me

## Overview

Use this skill to turn a vague idea into a compact, buildable brief. It combines the `grill-me` questioning style with an agentic operations loop for n8n workflows, app/tool setup, homelab projects, integrations, and agent workflows.

`brief-me` is the first skill in a package:

1. **brief-me** — ask the right questions and produce the build brief.
2. **build-me** — execute the smallest safe slice, verify, and iterate.
3. **ship-me** — release/activate/expose with final gates and rollback.
4. **maintain-me** — monitor after shipping and auto-fix simple failures when safe.

Core principle:

```text
Grill the idea → write the brief → build the smallest safe slice → verify → ship → maintain
```

## When to Use

Use this skill when an authorized user:

- starts a new project, automation, workflow, integration, or self-hosted app setup;
- says "brief me", "grill me", "turn this into a plan", or asks to build something agentically;
- wants an n8n workflow or no-code/low-code automation;
- wants a new tool/app installed on a host;
- wants multiple agents to understand and execute the same task;
- needs side-effect, approval, idempotency, or rollback boundaries before implementation.

Do not use this skill to execute the whole project by itself. Use it to produce the brief and decide whether to hand off automatically to `build-me`.

## Questioning Style

Follow `grill-me` behavior:

1. **Always inspect first**: Run `skill_view`, `read_file`, `session_search` to answer what you can **before** asking the user anything.
2. Ask one important question at a time. Never ask something you already found in documentation, config, memory or session history.
3. For every question, provide your recommended answer.
4. Stop asking once the first safe build slice is clear.
5. Produce a brief, not a meandering conversation transcript.
6. Never automatically delegate or hand off to another agent. This skill runs on the agent that received the user request.

Example:

```text
Question 1 — What should trigger this workflow?
Recommended answer: Start with a Manual Trigger first, then add the real trigger after output is verified.
```

## Automatic Handoff Rule

`brief-me` may hand off to `build-me` automatically when the next step is low-risk.

Low-risk includes:

- read-only inspection;
- creating draft files/configs with placeholders;
- creating inactive n8n workflows;
- testing with fake/sample data;
- local health checks;
- safe test sends only to explicitly approved destinations.

Do **not** automatically hand off when the next step would:

- activate a workflow with real side effects;
- send messages to real recipients outside an approved test destination;
- post publicly;
- delete or overwrite workflows, credentials, files, containers, or database rows;
- change DNS, Cloudflare routes, tunnels, or public exposure;
- run production database migrations/backfills;
- restart critical services;
- print, move, or store secrets.

Those require `ship-me` or explicit approval.

## Mandatory MoE Stage Gate

At the final result of every package stage, create or update **one redacted Google Doc per task** in the configured private Drive folder. The document is the canonical handoff record and must hold separate reports from **GPT-5.6 Sol** (contract, scope, approval boundaries, next-stage readiness) and **DeepSeek V4 Pro** (operational evidence, feasibility, idempotency, rollback, and safety).

Create a `stage-gate/v1` JSON input validated by `schemas/stage-gate-record.v1.json` and `contracts/stage-contracts.v1.json`, then run `python "${BRIEF_ME_PACKAGE_ROOT:-$HOME/brief-me}/scripts/moe_stage_gate.py" --stage brief-me --artifact <redacted-record.json> --task-title "<task title>"`. Both models must return `PASS` before handoff. `NEEDS_REVISION` loops back (maximum three attempts), `NEEDS_APPROVAL` pauses for the user, and `EVALUATOR_ERROR` blocks until explicitly resolved; shipping is always blocked. Keep the two reports separate and never commit Drive IDs, task documents, or unredacted evidence.

## Durable Task Ledger Guardrail

For any Hermes agent task with 3+ steps, repo/file edits, cron/job changes, background processes, deployment, remote-host work, or an explicit “build/fix/verify” request, open a durable ledger entry before starting implementation:

```bash
~/.hermes/scripts/agent_task_ledger.py start \
  --title "<task title>" \
  --origin "<chat/session/source>" \
  --safe-auto-resume \
  --allowed-resume-actions "read_only_verify,retry_timeout,repo_validation,cron_validation,final_report,recover_from_transcript" \
  --check "slice1:<acceptance check>:<verification command/output>"
```

The brief must include acceptance checks that can be copied into the ledger. Do not claim the task is complete until the final blocker passes:

```bash
~/.hermes/scripts/agent_task_ledger.py check-final --task-id <task_id>
```

If a task is ambiguous, approval-gated, destructive, secret-bearing, public-facing, or involves real recipients, either omit `--safe-auto-resume` or include blocked actions so the watchdog alerts instead of resuming.

## The Brief-Me Loop

### 1. Capture Intent

Restate the idea in one sentence:

```text
You want <system> to do <action> when <trigger> happens, producing <output>, while avoiding <forbidden side effect>.
```

### 2. Classify the Domain

Pick the execution lane:

- **n8n workflow:** later load `automation-platform-operations` and `build-me`.
- **Self-hosted app/tool:** later load `linux-remote-system-operations` and `build-me`.
- **Agent workflow:** later load `subagent-driven-development` or agent-specific skills.
- **Recurring report/admin automation:** later load relevant productivity/database/email skills.
- **Code feature:** later load `writing-plans` and `test-driven-development`.

### 3. Define the First Useful Version

Make version one smaller than the dream:

- Manual trigger before real trigger.
- Draft output before live send.
- Local-only app before public URL.
- Sample payload before production data.
- One destination before many.
- One record before a backfill.

### 4. Define Verification

Every build slice needs observable proof:

- n8n execution output;
- execution ID;
- received test message;
- database row exists and no duplicate was created;
- `curl` health check;
- container/service logs;
- screenshot or UI state;
- dry-run output.

### 5. Define Approval Gates

Explicitly list what requires approval. At minimum:

- activation;
- public exposure;
- real recipients;
- production data mutation;
- deletion;
- DNS/tunnel changes;
- secret handling.

### 6. Produce the Brief

Use this format:

```markdown
# Brief: <name>

**Intent:** <one sentence>
**Domain:** <n8n/app setup/agent workflow/etc>
**First useful version:** <smallest testable outcome>

**Current-state inspection needed:**
- <read-only checks>

**Trigger/input:** <manual/webhook/schedule/email/etc>
**Output/side effects:** <message/database write/app action/etc>

**Allowed low-risk next actions:**
- <things build-me can do automatically>

**Approval-gated actions:**
- <things requiring user approval>

**Build slices:**
1. <slice> — verify by <check>
2. <slice> — verify by <check>
3. <slice> — verify by <check>

**Success criteria:**
- <observable success>

**Failure behavior:**
- <fail-closed behavior>

**Idempotency / duplicate policy:**
- <event ID, hash, row key, stop behavior>

**Credentials/secrets:**
- <credential names or approved stores only; no values>

**Rollback:**
- <disable workflow/revert compose/remove tunnel/etc>

**Next skill:** `build-me` / `ship-me` / `maintain-me`
```

## n8n Brief Template

```markdown
# Brief: <Workflow Name>

**Purpose:** <one sentence>
**Build status:** Inactive until tested.
**Trigger:** Manual first, then <real trigger>.
**Input sample:** <sample payload or how to obtain it>
**Actions:** <Postgres insert, Telegram message, API call, etc>
**Idempotency key:** <message ID/event ID/hash/etc>

**Build slices:**
1. Manual Trigger + sample payload — verify execution output.
2. Transform/validate — verify expected fields.
3. Dry-run action path — verify would-send/would-write output.
4. Safe test send or test write — verify exact destination/output.
5. Activation — use `ship-me` once tests pass.

**Failure behavior:** Invalid/missing input stops quietly or logs; no spam.
**Rollback:** Disable workflow; restore JSON backup if modifying an existing workflow.
```

## App/Tool Setup Brief Template

```markdown
# Brief: <Tool/App Name>

**Purpose:** <why this tool is being set up>
**Host:** <local host / VPS / workstation / server etc>
**Access policy:** Local-only first; public/tunnel exposure only after `ship-me` gates.

**Pre-flight inspection:**
- OS/reachability
- Docker/Compose or runtime availability
- disk/memory
- existing ports/services
- existing tunnels/DNS/routes
- secret storage route

**Build slices:**
1. Minimal config with placeholders — verify files contain no secret values.
2. Start locally — verify service/container is running.
3. Health check — verify local endpoint returns success.
4. Persistence check — restart and verify data survives.
5. External access — use `ship-me` after approval or low-risk internal criteria.

**Rollback:** Stop service, restore prior config, remove route/tunnel if created.
```

## Common Pitfalls

1. **Asking for everything before building.** Ask only until the first safe slice is clear.
2. **Building without a brief.** Multi-system work needs a shared artifact.
3. **Skipping current-state inspection.** Inspect safely rather than guessing.
4. **No idempotency.** Recurring automations need duplicate protection.
5. **No failure behavior.** Define what happens when inputs or APIs fail.
6. **Activating too early.** Use `ship-me` for release/activation gates.
7. **Secret leakage.** Document credential names/locations only, never values.
8. **Overbuilding v1.** Prove the path first, then expand.

## Verification Checklist

- [ ] Intent is one sentence.
- [ ] Domain is classified.
- [ ] First useful version is smaller than the full idea.
- [ ] Current-state inspection is listed and performed where safe.
- [ ] Trigger/input and output/side effects are explicit.
- [ ] Allowed low-risk next actions are explicit.
- [ ] Approval-gated actions are explicit.
- [ ] Build slices have verification methods.
- [ ] Idempotency/duplicate behavior is defined when relevant.
- [ ] Failure behavior is fail-closed where possible.
- [ ] Secrets are assigned to approved stores only.
- [ ] Rollback path is documented.
- [ ] Next skill is named.

## One-Line Reminder

```text
Ask until the first safe slice is clear, brief it, then let build-me verify it in the real world.
```
