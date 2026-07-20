# brief-me skill package

A Hermes skill package for turning vague project ideas into verified agentic execution loops — especially for n8n workflows, no-code/low-code automations, self-hosted app/tool setup, homelab operations, and multi-agent work.

## Skills

- `brief-me` — grill the idea into a compact build brief, with approval gates and first safe slice.
- `build-me` — execute the smallest safe slice using inspect → build → run → observe → fix loops.
- `ship-me` — release/activate/expose with final verification, rollback, and side-effect gates.
- `maintain-me` — create quiet monitoring/watchdogs and auto-fix simple failures when safe.

## Operating model

```text
brief-me → build-me → ship-me → maintain-me
```

The package translates the coding-agent loop into operational work:

```text
Vague idea → grilled questions → build brief → smallest safe slice → verified run → safe ship → quiet maintenance
```

## Install into Hermes

Clone this repo, then copy or symlink the skill directories into your Hermes skills folder:

```bash
mkdir -p ~/.hermes/skills/productivity
cp -R skills/productivity/brief-me ~/.hermes/skills/productivity/
cp -R skills/productivity/build-me ~/.hermes/skills/productivity/
cp -R skills/productivity/ship-me ~/.hermes/skills/productivity/
cp -R skills/productivity/maintain-me ~/.hermes/skills/productivity/
```

Start a new Hermes session after installing so the skill loader can see them.

## Use

Start with:

```text
Use brief-me. I want to build <workflow/app/tool/integration>.
```

The agent should ask one question at a time, recommend a default answer, produce a build brief, then automatically hand off to `build-me` for low-risk actions.

## Safety defaults

Low-risk actions can proceed automatically:

- read-only inspection;
- draft files/configs with placeholders;
- inactive n8n workflows;
- sample/fake data tests;
- local health checks;
- safe test sends to explicitly approved destinations.

Approval is required for public exposure, real recipients outside approved destinations, destructive changes, broad production data mutation, secrets movement/storage, DNS/tunnel changes, or critical restarts.

## Mandatory MoE stage gates

Every final stage result is evaluated in parallel by **GPT-5.6 Sol** (contract, scope, approval boundaries, next-stage readiness) and **DeepSeek V4 Pro** (operational evidence, feasibility, failure behavior, rollback, safety). The two reports remain separate. A stage advances only when both return `PASS`; revision, approval, and evaluator-error outcomes use explicit gates rather than a blended score.

Each workflow task has one private Google Doc as its canonical redacted record. Configure its Drive folder and evaluator settings outside the repository in `~/.hermes/brief_me_stage_reviews.private.json`; start from `brief_me_stage_reviews.private.json.example`. The generic implementation, schemas, prompt contracts, and test fixtures are public-safe:

```text
schemas/stage-gate-record.v1.json
contracts/stage-contracts.v1.json
prompts/
scripts/moe_stage_gate.py
scripts/google_doc_stage_record.py
tests/
```

Use `scripts/moe_stage_gate.py --help` for invocation details. The script validates the record locally, runs both evaluator calls in parallel, then appends the independent reports and canonical machine record to the task Doc. The runtime is invoked from the package checkout by default (`$HOME/brief-me`); set `BRIEF_ME_PACKAGE_ROOT` when the checkout is elsewhere. Never commit Drive IDs, task docs, raw evaluator prompts, or unredacted evidence.

## Public-release privacy gate

This repository is designed to be publicly shareable. Never commit local fleet target files, session evidence, credentials, personal/work details, hostnames, IP addresses, or direct identifiers.

Before every GitHub upload, run the fail-closed scanner against the tracked tree and staged diff. Supply any organization-specific prohibited terms from a local file that is **not** committed:

```bash
scripts/privacy_scan.py --staged --deny-terms-file ~/.hermes/brief_me_public_scan_terms.txt
```

Before changing repository visibility or rewriting history, also scan reachable history and commit identities:

```bash
scripts/privacy_scan.py --history --deny-terms-file ~/.hermes/brief_me_public_scan_terms.txt
```

The weekly self-improvement cron must run the same staged-release scan before it commits or pushes. The ignored private target configuration and deny-terms file stay outside this repository.

## License

MIT

## Optional self-improvement cron

You can run a weekly Hermes cron to review usage of this package across one or more configured agents, then improve the skills and push updates back to this repo.

The primary support script is:

```bash
scripts/brief_me_usage_collect.py
```

It collects compact, redacted skill-usage evidence, evidence-tag counts, package-integrity hashes, and bounded-improvement decision metadata. The cron prompt should abstract any work/personal details into reusable skill improvements and avoid committing sensitive content.

Treat the GitHub `main` branch as the **release record**. On every review, verify the local checkout and `origin/main` agree. If an installed package copy differs from the checkout, inspect that drift before overwriting it: publish a validated, generic improvement to GitHub first, then deploy the resulting commit to configured targets. Never create empty commits; a genuine no-change run should still report that GitHub is current.

Additional helpers:

- `scripts/verify_package_install.py` — verifies installed package hashes against the repo manifest. Public-safe by default; pass a private target config outside the repo for multi-agent fleets.
- `scripts/deploy_package_install.py` — creates per-target backups and deploys the four package skills from the local checkout to trusted configured targets; use it only after the source commit is pushed.
- `scripts/create_improvement_proposal.py` — writes proposal-mode output under `proposals/` when evidence is ambiguous or policy-changing.
- `scripts/append_review_log.py` — appends a local machine-readable JSONL review record, normally under `~/.hermes/state/brief_me_package_reviews.jsonl`.

Recommended policy: **bounded auto-improvement**.

- Auto-fix package drift when configured targets are missing package files or hashes do not match the repo manifest.
- Auto-commit only small, validated skill-text changes when there is concrete reusable evidence: repeated corrections, clear misuse, missing approval/verification gates, drift, or broken instructions.
- Create a proposal instead of editing when evidence is ambiguous, one-off, structural, or would change delivery/model/tool/secret-handling policy.
- Default to `no_change` when the week has usage but no concrete reusable improvement.

See `examples/self-improvement-cron.md` for the recommended cron prompt structure.
