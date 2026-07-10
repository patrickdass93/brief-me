# Improvement proposals

This directory is for proposal-mode output from the weekly self-improvement cron.

Create a proposal instead of editing skills directly when an improvement is plausible but ambiguous, one-off, structural, policy-changing, or too large for bounded auto-commit.

Expected filename:

```text
YYYY-MM-DD-brief-me-improvement.md
```

Each proposal should include:

- evidence summary;
- affected skill;
- suggested patch;
- why it was not auto-applied;
- validation/deployment notes.

The helper script can create the file:

```bash
scripts/create_improvement_proposal.py \
  --affected-skill package \
  --evidence-summary "One ambiguous handoff signal; no repeated failure." \
  --suggested-patch "Describe proposed minimal diff here." \
  --rationale "Insufficient repeated evidence for auto-edit."
```
