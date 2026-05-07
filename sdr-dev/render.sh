#!/usr/bin/env bash
# Render values-override.yaml.tmpl from .env using envsubst.
#
# Usage: dev/sdr/render.sh
#
# Reads the SDR_* variables expected by values-override.yaml.tmpl from the
# current environment. The Makefile target `make sdr-render` `source`s .env
# before invoking this script, so both:
#
#   $ source .env && dev/sdr/render.sh
#   $ make sdr-render
#
# work. Output is written to dev/sdr/values-override.yaml (gitignored).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPL="${SCRIPT_DIR}/values-override.yaml.tmpl"
OUT="${SCRIPT_DIR}/values-override.yaml"

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
