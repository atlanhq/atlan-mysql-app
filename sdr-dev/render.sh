#!/usr/bin/env bash
# Render values-override.yaml.tmpl from .env using envsubst.
#
# Usage: sdr-dev/render.sh
#
# Reads the SDR_* variables expected by values-override.yaml.tmpl from the
# current environment. The Makefile target `make sdr-render` `source`s .env
# before invoking this script, so both:
#
#   $ source .env && sdr-dev/render.sh
#   $ make sdr-render
#
# work. Output is written to sdr-dev/values-override.yaml (gitignored).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPL="${SCRIPT_DIR}/values-override.yaml.tmpl"
OUT="${SCRIPT_DIR}/values-override.yaml"

# ── Image ref — accept the natural "repo:tag" form and split for the chart.
# Chart YAML expects image.repository / image.tag separately, so we take a
# single combined SDR_DEPLOYMENT_IMAGE (e.g. atlanhq/atlan-mysql-app:main-abc)
# and derive the two values that the template substitutes.
if [[ -n "${SDR_DEPLOYMENT_IMAGE:-}" ]]; then
  if [[ "$SDR_DEPLOYMENT_IMAGE" != *:* ]]; then
    echo "Error: SDR_DEPLOYMENT_IMAGE must be in 'repo:tag' form" >&2
    echo "  got:  $SDR_DEPLOYMENT_IMAGE" >&2
    echo "  e.g.: atlanhq/atlan-mysql-app:main-decd72f" >&2
    exit 1
  fi
  export SDR_IMAGE_REPO="${SDR_DEPLOYMENT_IMAGE%:*}"
  export SDR_IMAGE_TAG="${SDR_DEPLOYMENT_IMAGE##*:}"
fi

# ── Required env vars — fail fast with a clear message ───────────────────
REQUIRED_VARS=(
  SDR_RELEASE_NAME
  SDR_DEPLOYMENT_NAME
  SDR_TENANT_DOMAIN
  SDR_INSTANCE_NAME
  SDR_S3_BUCKET
  SDR_S3_REGION
  SDR_IMAGE_REPO
  SDR_IMAGE_TAG
  SDR_MYSQL_USERNAME
  SDR_MYSQL_PASSWORD
)

missing=()
for v in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    missing+=("$v")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: required SDR_* vars not set in environment:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo "" >&2
  echo "Set them in .env (see .env.example for the full list) and re-run:" >&2
  echo "  source .env && make sdr-render" >&2
  echo "" >&2
  echo "Note: SDR_IMAGE_REPO + SDR_IMAGE_TAG are derived from" >&2
  echo "SDR_DEPLOYMENT_IMAGE (repo:tag form) — set that one instead." >&2
  exit 1
fi

if ! command -v envsubst >/dev/null 2>&1; then
  echo "Error: envsubst not found (install gettext)." >&2
  echo "  macOS:  brew install gettext" >&2
  echo "  ubuntu: apt-get install gettext-base" >&2
  exit 1
fi

# Restrict substitution to SDR_* vars so we don't accidentally interpolate
# literal $-references in YAML (e.g. helm templating like {{ .Values.foo }}
# is safe, but a bare "$shell-like" string could trip up unrestricted mode).
SUBST_VARS=$(printf '${%s} ' "${REQUIRED_VARS[@]}")
envsubst "$SUBST_VARS" < "$TMPL" > "$OUT"

echo "Rendered: $OUT"
echo "Release:  ${SDR_RELEASE_NAME} (deployment=${SDR_DEPLOYMENT_NAME})"
echo "Tenant:   ${SDR_TENANT_DOMAIN}"
echo "Image:    ${SDR_IMAGE_REPO}:${SDR_IMAGE_TAG}"
