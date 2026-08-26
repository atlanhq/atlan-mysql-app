## Mandatory pre-commit review (L1–L4)

Before ANY `git commit`, the current changes MUST pass the `connector-review`
skill: the L1 conformance suite plus every applicable L2/L3/L4 review rule.
A PreToolUse hook blocks unreviewed commits; editing after a review invalidates
it, so re-review after fixes.

- L2/L4 rules: fetched from `atlanhq/application-sdk@main` into
  `.mothership/.cache/review-rulesets/` by `scripts/fetch-review-rules.sh`.
- L3 rules: `.mothership/review-rulesets/connector-app/` (this repo).
- Never restate rule text in this file or in prompts — the rule files are the
  only authority. If a rule seems wrong, change it in its source repo.
- Local review is fast feedback. The PR-label CI review remains authoritative.
- Emergency bypass (humans only, discouraged): `SKIP_CONNECTOR_REVIEW=1`.
