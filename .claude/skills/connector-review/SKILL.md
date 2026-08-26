---
name: connector-review
description: Mandatory pre-commit review of the working diff against the L1 conformance suite and the L2/L3/L4 connector review rulesets. Run before every git commit; the commit gate blocks unreviewed changes. Use when the user says review, pre-commit review, or when a commit is blocked by the review gate.
---

# Connector review (local, L1–L4)

Review the current change exactly the way the CI connector reviewer does. Rule
files are the only authority — never review from memory of what a rule says.

## 1. Scope

`git diff HEAD --name-only` plus `git diff --cached --name-only` (union). If both
are empty, use `git diff origin/main...HEAD --name-only`. The changed files and
their diffs are the only commentable scope; read surrounding code to verify, not
to widen scope.

## 2. Load rules

1. Run `scripts/fetch-review-rules.sh` (safe to run every time; it is a no-op
   pinned to cache when offline).
2. L2: every rule file in `.mothership/.cache/review-rulesets/connector-app/rules/`.
   L4: every rule file in `.mothership/.cache/review-rulesets/platform/rules/`.
   L3: every rule file in `.mothership/review-rulesets/connector-app/rules/`
   (this repo, committed).
3. Select a rule when any frontmatter glob matches a changed file; `globs: []`
   means always selected. Honor `.mothership/review-rulesets/connector-app/suppressions.yaml`
   if present: skip a `suppressible: true` rule listed there with an unexpired
   `expires` date, and say so in the report.
4. If the L2/L4 cache is missing and cannot be fetched, review L1+L3 only and
   put "L2/L4 NOT REVIEWED — rules unavailable" at the top of the report.

## 3. L1 — conformance suite

Run:

```bash
uv sync --quiet && uv run --with "atlan-application-sdk-conformance" -- \
  atlan-application-sdk-conformance detect --repo . \
  --output /tmp/conformance.sarif --exit-zero > /dev/null
```

Every flag here is load-bearing:
- Omitting `--series` runs every registered check (the CLI default). NEVER pass a
  concatenated series string like `CEPODLTIBKS` — `--series` takes comma-separated
  letters, and an unknown string silently matches ZERO checks and exits 0.
- `uv run --with ...` (NOT `uvx`) runs the detector inside the project's synced
  environment — the same form CI's needs-env legs use. `uvx` is an isolated env,
  so dependency-resolution checks (D-series) silently see zero project
  dependencies and under-report.
- `> /dev/null` is required: even with `--output`, the CLI prints its full human
  report to stdout (hundreds of findings, tens of thousands of tokens on a real
  connector repo). The SARIF file is the only output you read; stderr stays
  visible for real errors.
- `--exit-zero` is deliberate: the exit code covers the whole repo, but this
  review gates on the diff (below), so the SARIF is the signal, not the exit
  code.

Never print the SARIF — it can be hundreds of KB. Extract only what the review
scope needs:

```bash
python3 - <<'EOF'
import json, subprocess
changed = set(subprocess.run(
    "git diff HEAD --name-only; git diff --cached --name-only",
    shell=True, capture_output=True, text=True).stdout.split())
if not changed:
    changed = set(subprocess.run(
        "git diff origin/main...HEAD --name-only",
        shell=True, capture_output=True, text=True).stdout.split())
sarif = json.load(open("/tmp/conformance.sarif"))
run = sarif["runs"][0]
levels = {r["id"]: (r.get("defaultConfiguration") or {}).get("level", "warning")
          for r in run["tool"]["driver"].get("rules", [])}
in_scope, outside = [], 0
for res in run.get("results", []):
    locs = res.get("locations") or [{}]
    uri = ((locs[0].get("physicalLocation") or {}).get("artifactLocation") or {}).get("uri", "")
    line = ((locs[0].get("physicalLocation") or {}).get("region") or {}).get("startLine")
    if uri in changed:
        level = res.get("level") or levels.get(res.get("ruleId"), "warning")
        in_scope.append((res.get("ruleId"), level,
                         uri, line, (res.get("message") or {}).get("text", "")[:200]))
    else:
        outside += 1
for row in in_scope:
    print("L1 %s [%s] %s:%s — %s" % row)
print(f"L1 summary: {len(in_scope)} finding(s) in changed files; "
      f"{outside} pre-existing finding(s) outside this change — not blocking.")
EOF
```

Gate semantics (mirrors CI, which scopes each series to changed paths):
- `error`-level findings in CHANGED files → BLOCKER findings (cite the check id).
- `warning`-level findings in changed files → observations.
- Findings in unchanged files → the single summary line only. Never itemize them,
  never block on them.
Never re-derive or restate the suite's checks as review opinions — consume the
SARIF output.

## 4. Pass A — rule-guided

Walk EVERY selected rule and record a verdict:
- `not_applicable` — the rule's subject does not appear in the changed files.
- `checked` — subject appears; you inspected the matching changed code and found
  no defect.
- `finding` — you cite the rule id in a finding.

Rules are violated indirectly more often than literally. For each rule also check:
scale-not-snapshot (a value small today that grows with tenant/source size),
distance (the violation one or two calls away from the diff), and removed
guardrails (deleting or weakening the check the rule relies on).

## 5. Pass B — open bug hunt

One independent pass over the diff for concrete correctness defects no rule names
(wrong logic, data loss, races). Prefix these `GENERAL-`. When you confirm one
defect, check the diff's sibling call sites for the same shape.

## 6. Verify, then report

For every candidate finding: quote the exact lines that make it true, attempt one
honest refutation, drop it if you cannot quote evidence or the defect predates
this change. Severity starts at the rule's `severity:` frontmatter.

Report format:
1. Verdict line: `REVIEW PASS` or `REVIEW FAIL (N blockers)`.
2. Findings: `[SEVERITY] RULE-ID file:line — one-line defect + concrete fix`.
3. Coverage table: one row per selected rule with its verdict.
4. Skipped/suppressed rules and any unavailable levels, named explicitly.

## 7. Write the review marker (required — the commit gate reads it)

```bash
python3 - <<'EOF'
import json, subprocess, datetime, os
state = subprocess.run(
    "git rev-parse HEAD; git diff HEAD; git diff --cached",
    shell=True, capture_output=True, text=True).stdout
import hashlib
os.makedirs(".mothership/.cache", exist_ok=True)
lock = {}
try: lock = json.load(open(".mothership/.cache/rules.lock"))
except Exception: pass
json.dump({
    "state_hash": hashlib.sha256(state.encode()).hexdigest(),
    "verdict": "REPLACE_WITH_PASS_OR_FAIL",
    "sdk_rules_sha": lock.get("sha"),
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, open(".mothership/.cache/last-review.json", "w"))
EOF
```

Set `verdict` to `PASS` only when there are zero unresolved BLOCKER findings.
Fix blockers, re-run this skill, and only then commit.
