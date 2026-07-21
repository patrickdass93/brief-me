# Runtime Bundle and Fleet Audit Implementation Plan

> **For Hermes:** Build only generic package code and run a read-only audit. Do not install, replace, activate, restart, migrate, send, or write anything on remote targets.

**Goal:** Extend the brief-me package so it can *later* distribute the local Task Runtime beside the four skills, and add a generic read-only readiness auditor for default/profile Hermes roots.

**Architecture:** Keep `scripts/task_runtime.py` as the single source. The package deploy helper bundles it as a staged runtime artifact and, when eventually invoked without `--dry-run`, installs it under each target profile root at `runtime/task-runtime/task_runtime.py` with a local backup. Add a separate auditor that reads only filesystem/runtime capability metadata and never opens private config files or contacts external services beyond the explicit SSH transport.

**Safety boundary:** This build only exercises local temporary directories and explicit SSH read-only commands. Target definitions live in an ignored private JSON file. The auditor reports booleans, versions, and hashes only—never environment/config values, tokens, credentials, prompts, task contents, or private Docs.

---

### Task 1: Add failing distribution tests

**Files:**
- Create: `tests/test_runtime_distribution.py`
- Modify later: `scripts/deploy_package_install.py`
- Modify later: `scripts/verify_package_install.py`

**Tests:**
- the archive includes all four skills and exactly one runtime file;
- local deployment dry-run declares skill and runtime installation without changing the target root;
- local deployment copies the runtime file and creates a backup when using a temporary target root;
- package verification reports a distinct runtime hash/exists status;
- readiness probe returns only safe booleans/versions/hashes and supports a named profile root.

**Verification:** `python3 tests/test_runtime_distribution.py` fails before implementation, then passes after implementation.

### Task 2: Make runtime distribution atomic with the skill package

**Files:**
- Modify: `scripts/deploy_package_install.py`
- Modify: `scripts/verify_package_install.py`

**Requirements:**
- archive `scripts/task_runtime.py` as `runtime/task_runtime.py`;
- install it under `<profile-root>/runtime/task-runtime/task_runtime.py`;
- back up existing runtime directory alongside skill backups;
- preserve `--dry-run` as side-effect-free;
- fail before any replacement if the staged runtime file is absent;
- expose runtime hash/readiness separately from skill hash sync.

### Task 3: Add a generic read-only readiness auditor

**Files:**
- Create: `scripts/audit_runtime_readiness.py`
- Modify: `README.md`

**Requirements:**
- accept a private `--config` file or inline local target;
- support local, POSIX SSH, and Windows-OpenSSH-to-WSL targets;
- inspect default/profile root independently;
- report Python version, SQLite version, Hermes CLI availability, package-skill existence/hashes, runtime existence/hash, ledger/watchdog existence, state-path accessibility, and private-stage-config *presence only*;
- prohibit target configuration paths outside the provided profile root and avoid reading private config contents;
- use no remote write, no creation, no credential transfer, no model call, and no alert/send.

### Task 4: Run audit using private local target data

**Files:**
- Create outside repository: `~/.hermes/tasks/<task-id>/fleet-targets.private.json`
- Create outside repository: `~/.hermes/tasks/<task-id>/fleet-capability-matrix.json`

**Targets:** the approved target matrix, including both default and named-profile roots.

**Verification:** all eight targets receive a `ready`, `drift`, or `blocked` status with an evidence reason; no secret values appear in the matrix.

### Task 5: Package verification and gate

**Files:**
- Modify: `README.md`
- Create outside repository: build-stage record

**Verification:**
- full unit suite passes;
- local temporary deploy test and real `--dry-run` pass;
- privacy scanner passes on staged source;
- repo diff contains no fleet hostnames, agent names, target config, or task evidence;
- build-me dual evaluator gate passes.

**Rollback:** revert the final local source commit(s); delete only task-local audit artifacts. There is no remote rollback because this stage performs no remote writes.
