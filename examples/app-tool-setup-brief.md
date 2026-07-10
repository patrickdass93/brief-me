# Brief: Example App/Tool Setup

**Intent:** Run a new self-hosted tool locally first, then expose only after verification.
**Domain:** App/tool setup
**First useful version:** Local Docker Compose service with passing health check.

**Current-state inspection needed:**
- Host reachability and OS
- Docker/Compose availability
- Disk/memory
- Existing ports/services
- Existing tunnel/DNS routes
- Secret storage route

**Allowed low-risk next actions:**
- Create local compose/config with placeholders
- Start local service
- Run local health check
- Inspect logs

**Approval-gated actions:**
- Public URL/tunnel/DNS
- Real user access
- Production data import
- Secret movement/storage

**Build slices:**
1. Minimal config — verify no secret values in files.
2. Start service — verify container/service running.
3. Health check — verify local endpoint success.
4. Persistence — restart and verify state survives.
5. Ship — expose/activate via ship-me.
6. Maintain — create quiet watchdog via maintain-me.

**Rollback:** Stop service, restore config backup, remove route/tunnel if created.
