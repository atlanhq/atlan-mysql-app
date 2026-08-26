#!/usr/bin/env bash
# PreToolUse gate: block `git commit` unless the current change state was reviewed.
# Exit 0 = allow. Exit 2 = block (stderr goes back to Claude).
set -uo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)"

# Match a real `git commit` invocation in command position (start of command
# or after ; & | && || or a subshell open), including through common wrappers
# (VAR=val prefixes, env, sudo, command, nohup and their simple flags) — but
# not mere mentions of the words, otherwise `grep -rn "git commit" docs/`
# gets blocked and costs a full review.
printf '%s' "$cmd" | grep -qE '(^|[;&|(]|&&|\|\|)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|sudo[[:space:]]+|command[[:space:]]+|env[[:space:]]+|nohup[[:space:]]+|-[A-Za-z-]+(=[^[:space:]]+)?([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*git([[:space:]]+-[A-Za-z-]+([=][^[:space:]]*)?([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+commit([[:space:]]|$)' || exit 0
[ "${SKIP_CONNECTOR_REVIEW:-0}" = "1" ] && exit 0
case "$(git branch --show-current 2>/dev/null)" in wip/*) exit 0 ;; esac

marker=".mothership/.cache/last-review.json"
if [ ! -f "$marker" ]; then
  echo "BLOCKED: no connector review found. Run the connector-review skill on the current changes, then retry the commit." >&2
  exit 2
fi

state_hash="$( (git rev-parse HEAD; git diff HEAD; git diff --cached) 2>/dev/null | shasum -a 256 | cut -d' ' -f1)"
ok="$(python3 - "$marker" "$state_hash" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
print("yes" if m.get("state_hash") == sys.argv[2] and m.get("verdict") == "PASS" else "no")
EOF
)"
if [ "$ok" != "yes" ]; then
  echo "BLOCKED: changes were edited after the last review, or the last review did not PASS. Re-run the connector-review skill, then retry the commit." >&2
  exit 2
fi
exit 0
