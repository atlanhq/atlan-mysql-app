#!/usr/bin/env bash
# SessionStart: non-blocking freshness nudge for the fetched L2/L4 rules.
set -uo pipefail
lock=".mothership/.cache/rules.lock"
if [ ! -f "$lock" ]; then
  echo "Review rules not fetched yet — run scripts/fetch-review-rules.sh before the first review."
  exit 0
fi
head="$(gh api repos/atlanhq/application-sdk/commits/main --jq .sha 2>/dev/null || true)"
pinned="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("sha",""))' "$lock" 2>/dev/null)"
if [ -n "$head" ] && [ -n "$pinned" ] && [ "$head" != "$pinned" ]; then
  echo "L2/L4 review rules are stale (SDK main moved) — run scripts/fetch-review-rules.sh."
fi
exit 0
