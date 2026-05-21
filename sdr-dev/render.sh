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
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TMPL="${SCRIPT_DIR}/values-override.yaml.tmpl"
OUT="${SCRIPT_DIR}/values-override.yaml"

# Conflict-proof: when invoked directly (without `make sdr-render`), unset
# every SDR_* env var in the current shell before reading .env. A removed or
# commented line in .env can therefore never be silently overridden by a
# stale export from a prior `source .env`.
while IFS='=' read -r v _; do unset "$v"; done < <(env | grep -E '^SDR_[A-Z_]+=' || true)
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${PROJECT_ROOT}/.env"
  set +a
fi

# SDR_RELEASE_NAME is the user-facing knob. Defaults to "mysql-app-sdr-dev".
# The deployment suffix (used Atlan-side) is derived by stripping the prefix.
SDR_RELEASE_NAME="${SDR_RELEASE_NAME:-mysql-app-sdr-dev}"
if [[ "$SDR_RELEASE_NAME" != mysql-app-sdr-?* ]]; then
  echo "Error: SDR_RELEASE_NAME must start with 'mysql-app-sdr-' and have a non-empty suffix." >&2
  echo "  got:   $SDR_RELEASE_NAME" >&2
  echo "  e.g.:  mysql-app-sdr-dev, mysql-app-sdr-staging" >&2
  exit 1
fi
SDR_DEPLOYMENT_NAME="${SDR_RELEASE_NAME#mysql-app-sdr-}"
export SDR_RELEASE_NAME SDR_DEPLOYMENT_NAME

# ── Required env vars — fail fast with a clear message ───────────────────
REQUIRED_VARS=(
  SDR_DEPLOYMENT_NAME
  SDR_TENANT_DOMAIN
  SDR_INSTANCE_NAME
  SDR_S3_BUCKET
  SDR_S3_REGION
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
# Includes SDR_RELEASE_NAME (auto-derived above) since the template references it.
SUBST_VARS=$(printf '${%s} ' "${REQUIRED_VARS[@]}" SDR_RELEASE_NAME)
envsubst "$SUBST_VARS" < "$TMPL" > "$OUT"

echo "Rendered: $OUT"
echo "Release:  ${SDR_RELEASE_NAME} (deployment=${SDR_DEPLOYMENT_NAME})"
echo "Tenant:   ${SDR_TENANT_DOMAIN}"
echo "Tag:      ${SDR_IMAGE_TAG}"
