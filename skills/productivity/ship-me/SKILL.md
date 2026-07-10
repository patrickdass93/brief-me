---
name: ship-me
description: Use after build-me when a workflow, automation, app/tool, or integration is ready for activation, release, public exposure, or handoff with final verification and rollback gates.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [shipping, release, activation, deployment, verification, rollback]
    related_skills: [brief-me, build-me, maintain-me, automation-platform-operations, cloudflare-edge-operations]
---

# Ship Me

## Overview

Use this skill after `build-me` has produced a tested slice and the project is ready to activate, expose, deploy, or hand off. `ship-me` is the release gate for non-code and ops work.

Core principle:

```text
Do not ship because it was built. Ship because it was verified, rollback is clear, and side effects are approved or low-risk.
```

Default: `ship-me` may activate **low-risk internal workflows** after tests pass. Anything beyond that requires explicit approval.

## When to Use

Use when preparing to:

- activate an n8n workflow;
- expose a local app through a URL/tunnel/DNS route;
- send real messages beyond approved test destinations;
- enable schedules or recurring runs;
- deploy a service for ongoing use;
- make a workflow/app available to other agents or users;
- convert a working draft into a live system.

Do not use for initial building; use `build-me`. Do not use for long-term monitoring; use `maintain-me`.

## Shipping Policy

### Can ship automatically when all are true

`ship-me` may activate without asking when:

- the item is low-risk and internal;
- `brief-me`/`build-me` defined this as allowed;
- tests passed with real evidence;
- side effects are limited and reversible;
- no public exposure, real external recipients, production deletion, or broad mutation is involved;
- rollback is documented.

Examples:

- activating an internal no-send workflow that only logs state;
- enabling a quiet health-check workflow that alerts only to an approved destination;
- enabling a local-only service after health checks pass;
- activating a workflow that writes to a test/staging target.

### Must ask before shipping when any are true

Require explicit approval before:

- public URL, DNS, Cloudflare, reverse tunnel, or internet exposure;
- messages to real users/channels outside approved test/alert destinations;
- LinkedIn/social/public posts;
- production database writes, migrations, deletes, or backfills;
- deleting workflows/config/data;
- storing/moving secrets;
- restarting critical services;
- anything with cost, rate-limit, privacy, or reputational impact.

## The Ship-Me Gate

### 1. Re-read the Brief, Ledger, and Build Evidence

Confirm:

- intended outcome;
- tested build slices;
- durable task ledger status and pending checks, if a ledger-backed task exists;
- execution IDs/commands/logs;
- side effects already performed;
- approval gates;
- rollback.

If shipping completes a ledger-backed task, update/close the ledger only after post-ship verification, then run:

```bash
~/.hermes/scripts/agent_task_ledger.py check-final --task-id <task_id>
```

If approval is needed, mark the relevant ledger check `blocked` and do not enable safe auto-resume for that action.

### 2. Final Pre-Ship Verification

Depending on domain:

- n8n: workflow ID/name, active state, credentials metadata, recent execution success, idempotency, bad-input behavior.
- App/tool: local health endpoint, logs clean, restart policy, persistence, port ownership, auth enabled.
- Public exposure: local success first, route/tunnel/DNS target correct, auth in place, no admin console exposed accidentally.
- Messaging/social: destination verified, content reviewed, rate/noise controls present.

### 3. Backup or Rollback First

Before activation/exposure:

- export n8n workflow JSON if modifying existing workflow;
- copy compose/config files;
- capture previous route/DNS/tunnel state;
- document disable command;
- know how to revert.

### 4. Ship the Smallest Release

Activate/expose only the minimum necessary:

- one workflow, not all workflows;
- one schedule, not broad triggers;
- local/internal first;
- one approved destination;
- one route/domain;
- constrained permissions.

### 5. Post-Ship Verification

Immediately verify the shipped state:

- workflow active and next trigger schedule correct;
- successful execution or safe dry run;
- external URL loads expected page and auth works;
- message delivered to intended destination only;
- database row/state changed exactly as expected;
- logs have no new errors.

### 6. Handoff to Maintain-Me

After shipping, decide whether `maintain-me` should create monitoring/watchdogs, backup checks, or periodic health summaries.

## Ship Report Format

```markdown
# Ship Report: <name>

**Decision:** SHIPPED / NEEDS APPROVAL / BLOCKED
**Scope shipped:** <workflow/service/route/etc>
**Why allowed:** <low-risk internal or approved by user>
**Pre-ship evidence:** <execution IDs/commands/logs>
**Backup/rollback:** <exact disable/revert path>
**Post-ship verification:** <real observed output>
**Remaining risks:** <concise>
**Maintain-me handoff:** <watchdog/backup/checks needed or none>
```

## n8n Shipping Checklist

- [ ] Workflow JSON backup exists if modifying an existing workflow.
- [ ] Workflow ID/name verified.
- [ ] `active` state before and after is known.
- [ ] Test execution succeeded.
- [ ] Idempotency/duplicate handling exists for recurring workflows.
- [ ] Bad input fails closed.
- [ ] Destination is correct and approved.
- [ ] Activation is low-risk internal or explicitly approved.
- [ ] Post-activation execution/schedule was verified where possible.

## App/Tool Shipping Checklist

- [ ] Local health passed before exposure.
- [ ] Logs inspected.
- [ ] Persistence/restart behavior verified when relevant.
- [ ] Auth/admin setup understood.
- [ ] Public route/tunnel/DNS requires approval unless already scoped as internal/low-risk.
- [ ] Rollback command documented.
- [ ] Post-exposure URL/route verified.

## Common Pitfalls

1. **Shipping from vibes.** Passing build output is not enough; run the ship gate.
2. **No rollback.** If you cannot disable/revert, do not ship.
3. **Activating noisy automations.** Verify idempotency and failure behavior first.
4. **Public exposure before local health.** Local success first, exposure second.
5. **Wrong destination.** Verify chat/topic/user/URL/DB target exactly.
6. **Credential confusion.** Report credential names/locations, never values.
7. **Over-shipping.** Release the smallest live scope.

## Verification Checklist

- [ ] Build evidence exists.
- [ ] Approval requirement classified correctly.
- [ ] Backup/rollback captured.
- [ ] Final pre-ship checks passed.
- [ ] Shipped scope was minimal.
- [ ] Post-ship state verified with real output.
- [ ] Maintain-me handoff considered.
