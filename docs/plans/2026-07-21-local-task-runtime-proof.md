# Local Task Runtime Proof Implementation Plan

> **For Hermes:** Execute this plan in the local `~/brief-me` checkout only. Do not modify remote agents, installed skills, cron jobs, gateways, secrets, or active workflows.

**Goal:** Build a small, deterministic, SQLite-backed Task Runtime proof that records durable task state, transition events, idempotency keys, parent-child lineage, approval waits, and an import of existing JSON-ledger tasks.

**Architecture:** Add a standalone standard-library Python module at `scripts/task_runtime.py`. A local SQLite database is the authority for the proof. The module exposes a small Python API for tests and a JSON CLI for safe synthetic dry-run demonstration. It never calls tools, networks, Telegram, cron, LLMs, or external systems.

**Tech stack:** Python 3.13 standard library (`sqlite3`, `argparse`, `json`, `uuid`, `hashlib`, `datetime`), existing `unittest` suite.

**Safety boundary:** all test databases live in temporary directories. The CLI refuses non-synthetic consequential actions in dry-run mode. JSON-ledger import reads a specified local file; it does not delete, modify, or replace it.

---

### Task 1: Specify and test the durable state contract

**Objective:** Define expected behavior before implementation.

**Files:**
- Create: `tests/test_task_runtime.py`
- Create later: `scripts/task_runtime.py`

**Step 1:** Write focused tests for:
- first trigger creates a task and persistent event;
- duplicate idempotency key returns the original task without a second task;
- valid state transitions append events;
- invalid transitions fail closed;
- approval wait blocks forbidden actions until approval is received;
- child task receives parent ID;
- JSON-ledger import creates inspectable legacy tasks without mutating the source;
- dry-run lifecycle returns no external side effects and records duplicate/blocked-action evidence.

**Step 2:** Run `python3 tests/test_task_runtime.py`.

**Expected result:** FAIL because `scripts/task_runtime.py` does not yet exist.

### Task 2: Implement the minimal SQLite runtime

**Objective:** Add only the data model and operations required by Task 1.

**Files:**
- Create: `scripts/task_runtime.py`

**Implementation requirements:**
- SQLite schema: `tasks`, `events`, and unique `(agent_id, idempotency_key)` task index.
- Immutable task ID and optional parent task ID.
- Allowed state transitions defined in one mapping; unknown/invalid transitions raise a typed runtime error.
- `create_or_get_task`, `transition`, `await_approval`, `approve`, `create_child_task`, `get_task`, `list_events`, and `import_json_ledger` API.
- `run_dry_run` uses only an in-memory or caller-supplied local database and synthetic inputs; it never invokes external tools or side effects.
- JSON CLI output only; no secret/config reads.

**Step 1:** Implement the smallest code needed for the failing tests.

**Step 2:** Run `python3 -m unittest tests.test_task_runtime -v`.

**Expected result:** all focused tests PASS.

### Task 3: Exercise the proof through its CLI

**Objective:** Prove the runtime is usable as a local, inactive execution-layer adapter.

**Files:**
- Modify: `scripts/task_runtime.py`
- Modify: `tests/test_task_runtime.py`

**Step 1:** Add a `dry-run` CLI command which emits a JSON evidence object for synthetic task creation, duplicate suppression, approval blocking, approval/resume, and completion.

**Step 2:** Add a subprocess test that parses JSON output and asserts `external_side_effects == []`.

**Step 3:** Run focused tests and `python3 scripts/task_runtime.py dry-run --agent local-test`.

**Expected result:** JSON output contains a completed synthetic task, a duplicate pointer, blocked action evidence, and zero external side effects.

### Task 4: Verify and document the build result

**Objective:** Verify the package change and capture rollback details.

**Files:**
- Modify: `README.md` — add a short local-proof section and command.
- Create: redacted build-stage JSON outside the repository under `~/.hermes/tasks/<task-id>/`.

**Step 1:** Run full package tests: `python3 -m unittest discover -s tests -p 'test_*.py' -v`.

**Step 2:** Run `scripts/privacy_scan.py --staged --deny-terms-file ~/.hermes/brief_me_public_scan_terms.txt` only after creating an ignored local deny-terms file if absent; do not add target names or private facts to repository content.

**Step 3:** Inspect `git diff --check`, `git diff --stat`, `git status --short`, and confirm only intended generic/public-safe files changed.

**Rollback:** `git restore -- scripts/task_runtime.py tests/test_task_runtime.py README.md docs/plans/2026-07-21-local-task-runtime-proof.md`; no running process, remote agent, cron, or existing ledger is changed.

### Task 5: Build-stage evidence gate

**Objective:** Record real tests/diff evidence in the canonical task Doc.

**Files:**
- Create outside repo: `~/.hermes/tasks/<task-id>/build-stage-gate.json`

**Step 1:** Run the build-me stage gate against the existing canonical Doc ID.

**Expected result:** GPT-5.6 Sol and DeepSeek V4 Pro each return `PASS`.

**Stop condition:** A PASS gate authorizes only the later `ship-me` decision; it does not authorize remote deployment or activation.
