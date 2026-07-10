# Brief: Example n8n Workflow

**Intent:** When a sample event arrives, transform it and send a safe test notification.
**Domain:** n8n workflow
**First useful version:** Manual Trigger with sample JSON and dry-run output.

**Current-state inspection needed:**
- Existing workflows with similar purpose
- Available credential metadata, no secret values
- Approved test destination

**Trigger/input:** Manual Trigger first; real trigger later.
**Output/side effects:** Dry-run output first; safe test send only after approved.

**Allowed low-risk next actions:**
- Create inactive workflow
- Use sample payload
- Execute manually
- Inspect execution output

**Approval-gated actions:**
- Activation
- Real recipient sends
- Production database writes

**Build slices:**
1. Manual Trigger + sample payload — verify execution output.
2. Transform/validate fields — verify expected normalized JSON.
3. Dry-run notification text — verify message body.
4. Safe test send — verify delivery to approved destination.
5. Ship — activate only if low-risk internal or approved.

**Failure behavior:** Missing required fields stop quietly and log.
**Idempotency / duplicate policy:** Use upstream event ID or hash.
**Rollback:** Disable workflow; restore JSON backup.
