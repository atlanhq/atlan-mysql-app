#!/usr/bin/env bash
# Fetch the shared L2/L4 review rulesets from application-sdk@main, pinned to a SHA.
# L3 rules live in this repo (.mothership/review-rulesets/) and are never fetched.
set -euo pipefail

SDK_REPO="atlanhq/application-sdk"
CACHE_DIR=".mothership/.cache/review-rulesets"
LOCK_FILE=".mothership/.cache/rules.lock"

sha="$(gh api "repos/${SDK_REPO}/commits/main" --jq .sha 2>/dev/null || true)"
if [ -z "${sha}" ]; then
  if [ -f "${LOCK_FILE}" ]; then
    echo "WARN: cannot reach GitHub — keeping cached rules pinned at $(cat "${LOCK_FILE}")" >&2
    exit 0
  fi
  echo "ERROR: cannot reach GitHub and no cached rules exist. Review will run L1+L3 only." >&2
  exit 1
fi

mkdir -p "${CACHE_DIR}"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

for ruleset in connector-app platform; do
  gh api "repos/${SDK_REPO}/contents/.mothership/review-rulesets/${ruleset}?ref=${sha}" \
    --jq '.[] | select(.type=="file") | .path' | while read -r path; do
    mkdir -p "${tmp}/${ruleset}"
    gh api "repos/${SDK_REPO}/contents/${path}?ref=${sha}" --jq .content | base64 -d \
      > "${tmp}/${ruleset}/$(basename "${path}")"
  done
  rulesdir=".mothership/review-rulesets/${ruleset}/rules"
  gh api "repos/${SDK_REPO}/contents/${rulesdir}?ref=${sha}" \
    --jq '.[] | select(.type=="file") | .path' | while read -r path; do
    mkdir -p "${tmp}/${ruleset}/rules"
    gh api "repos/${SDK_REPO}/contents/${path}?ref=${sha}" --jq .content | base64 -d \
      > "${tmp}/${ruleset}/rules/$(basename "${path}")"
  done
done

rm -rf "${CACHE_DIR}"
mv "${tmp}" "${CACHE_DIR}"
trap - EXIT
printf '{"sdk_repo":"%s","sha":"%s","fetched_at":"%s"}\n' \
  "${SDK_REPO}" "${sha}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_FILE}"
echo "Fetched L2/L4 review rules at ${SDK_REPO}@${sha}"
