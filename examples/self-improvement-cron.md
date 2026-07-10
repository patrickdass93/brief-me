# brief-me package self-improvement cron

Recommended schedule: weekly at a time that fits your local timezone.

Model: choose a configured model that is reliable for small text edits and conservative review.

## Support script

Run the collector before the LLM prompt and inject its JSON output:

```bash
scripts/brief_me_usage_collect.py --days 14 --limit-per-agent 40
```

Use `--summary-only` for low-noise dry runs or routing checks.

The collector returns:

- redacted skill-usage snippets;
- per-agent evidence-tag counts;
- per-agent package file hashes;
- package-integrity comparison against the local repo manifest;
- bounded-improvement decision metadata.

## Recommended prompt policy

The cron should follow this loop:

```text
collect evidence
→ compare installed package hashes with the local checkout
→ fetch and verify the local checkout matches `origin/main`
→ classify evidence and any source drift
→ publish a validated generic local improvement before deploying it
→ patch the smallest relevant skill text only when evidence is strong
→ validate, commit, and push the release when content changed
→ reinstall/verify configured targets from that release when needed
→ report concise outcome
```

## Evidence thresholds

Default decision is `no_change`. Edit only when at least one concrete reusable signal exists:

| Decision | Required evidence |
|---|---|
| `no_change` | Usage exists, but no repeated correction, misuse, missing gate, drift, or broken instruction. |
| `auto_edit` | Small generic skill-text fix backed by concrete evidence: repeated correction, clear misuse, missing approval/verification gate, drift, or broken instruction. |
| `proposal` | Plausible improvement, but evidence is ambiguous, one-off, structural, or changes policy. |
| `drift_fix` | Any configured target is missing package files or hashes differ from the repo manifest. Inspect local source drift first: if it is a valid generic package improvement, commit and push it before redeploying; otherwise restore only after recording why it is not publishable. |

## Auto-commit boundaries

Allowed automatically:

- small validated edits to `skills/productivity/{brief-me,build-me,ship-me,maintain-me}/SKILL.md`;
- generic pitfalls, verification gates, examples, or handoff clarifications;
- package drift reinstall when the operator has configured trusted targets;
- repo docs/examples that explain the package policy.

Require a proposal instead of auto-editing for:

- large rewrites or new package structure;
- deleting/renaming skills;
- changing cron schedule, delivery, model, enabled toolsets, or secret handling;
- importing raw personal/work/customer/project details;
- adding new external integrations or side-effect policies.

Proposal files should go under:

```text
proposals/YYYY-MM-DD-brief-me-improvement.md
```

## Validation gates before commit/push

Before committing any automatic change:

1. Validate all four `SKILL.md` files have frontmatter with `name` and `description`.
2. Confirm descriptions are under 1024 characters.
3. Confirm skill files are under Hermes size limits.
4. Search the diff for secrets, tokens, private keys, raw chat IDs, private hostnames/IPs, customer/work details, and raw session snippets.
5. If `brief-me` changed, keep any root-level package `SKILL.md` mirror in sync if the repo uses one.
6. Run the collector in `--summary-only` mode as a smoke test.
7. Run package install verification against the configured target set:

   ```bash
   scripts/verify_package_install.py --config ~/.hermes/brief_me_package_targets.json --json
   ```

8. Commit and push only if validation passes.
9. After a successful push, deploy the committed package with backups, then re-run verification:

   ```bash
   scripts/deploy_package_install.py --config ~/.hermes/brief_me_package_targets.json
   scripts/verify_package_install.py --config ~/.hermes/brief_me_package_targets.json --json
   ```

## Proposal mode

When the decision is `proposal`, create a file under `proposals/` instead of changing skills directly:

```bash
scripts/create_improvement_proposal.py \
  --affected-skill package \
  --evidence-summary "<generic evidence summary; no raw snippets>" \
  --suggested-patch "<minimal proposed diff>" \
  --rationale "<why this was not auto-applied>"
```

Use `--dry-run` to test low-confidence candidates without writing a proposal.

## Weekly review log

Append one local JSONL record after every run so the maintainer can audit whether the job is improving over time or only rubber-stamping `no_change`:

```bash
scripts/append_review_log.py \
  --decision no_change \
  --repo-commit "$(git rev-parse --short HEAD)" \
  --integrity "5/5 targets OK" \
  --evidence-summary "No repeated correction or concrete failure pattern" \
  --changes none
```

Default log path: `~/.hermes/state/brief_me_package_reviews.jsonl`. Do not commit this local state file.

## Final report format

Keep Telegram output concise:

```markdown
✅ brief-me weekly improvement check

Decision: no_change / auto_edit / proposal / drift_fix
Evidence: <1-3 bullets>
Changes: <none or changed files>
Integrity: <N/N targets OK, commit SHA>
Next: <optional follow-up>
```

If nothing actionable was found, say so directly and do not inflate the report.
