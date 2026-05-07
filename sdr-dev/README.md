# SDR (Self-Deployed Runtime) — local dev/test setup

This directory holds everything needed to install the MySQL app as an SDR
deployment on a Kubernetes cluster you have access to (e.g. devex / vcluster).
It is **dev/test tooling only** — not shipped in the Docker image and not
deployed by CI.

## Layout

```
sdr-dev/
├── README.md                       this file
├── chart/                          patched copy of the mysql-app helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── deployment.yaml         patched: in-cluster Temporal, OAuth off
│       ├── dapr-components-cm.yaml patched: secretstore name, eventstore URL
│       └── …                       (unchanged from upstream)
├── values-override.yaml.tmpl       ${VAR} placeholders, committed
├── values-override.yaml            rendered output, GITIGNORED
└── render.sh                       envsubst wrapper (reads .env, validates)
```

## Required env vars

Add these to your `.env` (see [`.env.example`](../.env.example) for an
empty template). All are required by [`render.sh`](render.sh):

| Var | Example | Purpose |
|---|---|---|
| `SDR_RELEASE_NAME` | `mysql-sdr-dev` | helm release + chart `nameOverride`/`fullnameOverride` |
| `SDR_DEPLOYMENT_NAME` | `dev` | suffix appended to the agent name visible in Atlan |
| `SDR_TENANT_DOMAIN` | `tenant.atlan.com` | sets `global.atlanBaseUrl` |
| `SDR_INSTANCE_NAME` | `tenant-instance` | `ATLAN_INSTANCE_NAME` env on the pod |
| `SDR_S3_BUCKET` | `atlan-vcluster-…` | S3 bucket for app + lineage storage |
| `SDR_S3_REGION` | `ap-south-1` | S3 region for the dapr binding |
| `SDR_IMAGE_REPO` | `atlanhq/atlan-mysql-app` | container image to deploy |
| `SDR_IMAGE_TAG` | `main-<sha>` | image tag (use a known-good build) |
| `SDR_MYSQL_USERNAME` | `atlan` | MySQL credential (substituted into bundle) |
| `SDR_MYSQL_PASSWORD` | (secret) | MySQL credential (substituted into bundle) |

## Workflow

```bash
# 1. one-time per shell: load .env so render.sh sees the SDR_* vars
source .env

# 2. render values-override.yaml from .env
make sdr-render

# 3. install / upgrade the chart in-cluster (uses current kubectl context)
make sdr-install

# 4. inspect / interact
make sdr-status              # pod + helm status
make sdr-logs                # tail logs
make sdr-port-forward        # pod :8000 → localhost:8000

# 5. tear down when done
make sdr-uninstall
```

## Credential resolution: multi-key bundle vs single-key

The template defaults to **multi-key bundle** (PATTERN A in
[`values-override.yaml.tmpl`](values-override.yaml.tmpl)) — one env var
`MYSQL_SECRETS` holding a JSON dict of all credential fields. Widely
SDK-compatible.

If you're on SDK ≥ BLDX-968 (or 3.7+), you can switch to **single-key per
field** (PATTERN B): one env var per credential field, set
`key-type: single-key` in the Atlan UI workflow form, leave Secret Path
empty. Toggle the comment block in the template and re-render.

## Chart patches

The chart in [`chart/`](chart/) is a copy of `mysql-app` at
[`atlan-self-deployed-runtime`](https://github.com/atlanhq/atlan-self-deployed-runtime).
Two intentional deltas vs upstream:

1. **`templates/deployment.yaml`** — env vars are hardcoded for the in-cluster
   topology (`ATLAN_WORKFLOW_HOST` → `temporal-cluster-internal-frontend-headless.…`,
   `ATLAN_WORKFLOW_TLS_ENABLED=false`, `ATLAN_AUTH_ENABLED=false`). This avoids
   the Cloudflare gRPC path and the OAuth requirement on dev tenants.
2. **`templates/dapr-components-cm.yaml`** — `secretstore` component is named
   without prefix; `eventstore` URL points at the in-cluster service.

When the upstream chart changes, refresh by re-copying and re-applying these
patches. Diff against `atlan-self-deployed-runtime/mysql-app/` to inspect.

## Why this is in the repo, not in CI

SDR install is interactive — you need cluster access, and the values depend
on which tenant/vcluster you're testing against. Keeping the chart + templated
values here lets every contributor reproduce the setup from `.env` alone,
without copying YAML between repos. CI continues to use unit + e2e tests
(`make test`, `make test-e2e`).

## Excluded from the Docker image

[`/.dockerignore`](../.dockerignore) excludes `sdr-dev/` so the chart and
helper scripts never end up inside the runtime container. Same goes for
`tests/`, `local/`, etc.
