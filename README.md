<p align="center">
  <img src="./docs/images/mysql_logo.svg" alt="MySQL Logo" width="200" height="auto">
</p>

# MySQL Application


[![Tests](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/tests.yml/badge.svg)](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/tests.yml)
[![Build](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/build-image.yml/badge.svg)](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/build-image.yml)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

MySQL metadata extraction app built on [Atlan Application SDK v3](https://github.com/atlanhq/application-sdk). Extracts databases, schemas, tables, views, columns, and procedures from MySQL and transforms them into Atlan-compatible assets.

## Architecture

```
MySQLApp(SqlApp)                    MySQLHandler(Handler)
├── fetch_databases  @task          ├── test_auth      → AuthOutput
├── fetch_schemas    @task          ├── preflight_check → PreflightOutput
├── fetch_tables     @task          └── fetch_metadata  → SqlMetadataOutput
├── fetch_columns    @task
├── fetch_procedures @task
├── transform_*      @task  (asset mappers → JSONL)
└── upload_to_atlan  @task
```

- **`app/mysql.py`** — `MySQLApp` extends `SqlApp` with MySQL-specific SQL queries and asset mappers
- **`app/handlers/mysql.py`** — v3 handler for auth, preflight, and metadata endpoints
- **`app/clients/`** — `SQLClient` with basic, IAM user, and IAM role authentication
- **`app/sql/`** — SQL templates for metadata extraction

### Auth Support

| Auth Type | Description |
|-----------|-------------|
| `basic` | Username/password with SSL |
| `iam_user` | AWS IAM user → RDS auth token |
| `iam_role` | AWS STS assume role → RDS auth token |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [Dapr CLI](https://docs.dapr.io/getting-started/install-dapr-cli/)
- [Temporal CLI](https://docs.temporal.io/cli)
- Docker (optional, for testcontainers)

### Setup

```bash
git clone https://github.com/atlanhq/atlan-mysql-app.git
cd atlan-mysql-app
make install
```

### Local Development

Create a `.env` with your MySQL credentials:

```bash
export MYSQL_HOST="localhost"
export MYSQL_PORT="3306"
export MYSQL_USER="root"
export MYSQL_PASSWORD=""
```

Start the app (sets up Dapr creds, starts Temporal + Dapr, runs the app):

```bash
source .env && make dev
```

The app is available at `http://localhost:8000`.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/server/health` | GET | Health check |
| `/workflows/v1/auth` | POST | Test MySQL connectivity |
| `/workflows/v1/check` | POST | Preflight checks (auth + table access) |
| `/workflows/v1/metadata` | POST | Fetch schema list for UI |
| `/workflows/v1/configmaps` | GET | List configmaps |
| `/workflows/v1/start` | POST | Start extraction workflow |
| `/workflows/v1/status/{wf_id}/{run_id}` | GET | Check workflow status |

## Testing

### Unit Tests

```bash
make test        # 45 tests, 84%+ coverage
make test-cov    # with HTML coverage report
```

### Integration Tests (E2E)

Tests run against a real MySQL database. Two modes:

**With Docker (testcontainers — zero config):**

```bash
make test-e2e    # spins up MySQL container, seeds 5 DBs / 99 tables / 1500+ columns
```

**With external MySQL:**

```bash
source .env && make test-e2e    # uses MYSQL_HOST from .env
```

E2E tests validate:
- Health, auth, preflight, metadata, configmap endpoints
- Full workflow: start → poll → COMPLETED
- Extracted artifacts: raw parquet files per entity
- Transformed artifacts: JSONL with correct `typeName`, `qualifiedName`, `connectorName`
- Extraction report with entity counts and timings

### Remote E2E (vcluster)

```bash
make test-e2e-remote    # port-forwards to deployed app, runs e2e suite
```

Requires `APP_NAMESPACE`, `APP_DEPLOYMENT`, `REMOTE_CREDENTIAL_GUID` env vars.

### Self-Deployed Runtime (SDR)

For dev / test against a real tenant we ship a templated helm chart at
[`sdr-dev/`](sdr-dev/). All knobs are read from `.env` — no creds in
committed YAML.

```bash
make sdr-render              # render sdr-dev/values-override.yaml from .env
make sdr-install             # helm upgrade --install (current kubectl context)
make sdr-status              # pods + helm status
make sdr-logs                # tail logs
make sdr-port-forward        # SDR pod :8000 → localhost:8000
make sdr-uninstall           # helm uninstall (keeps namespace)
make sdr-teardown            # helm uninstall + delete namespace + remove rendered values
```

The `make sdr-*` targets re-source `.env` in a fresh subshell, so you don't need
to `source .env` between edits — just edit the file and re-run.

The `sdr-dev/` directory is excluded from the Docker image via
[`.dockerignore`](.dockerignore). The rendered `values-override.yaml`
(with substituted creds) is gitignored. See
[`sdr-dev/README.md`](sdr-dev/README.md) for required env vars, chart
patches, and credential-resolution patterns (multi-key bundle vs single-key).

## Project Structure

```
app/
├── mysql.py              # MySQLApp — SqlApp subclass with SQL queries + asset mappers
├── handlers/mysql.py     # v3 Handler — auth, preflight, metadata
├── clients/__init__.py   # SQLClient — basic + IAM user + IAM role auth
├── constants.py          # DATABASE_PLACEHOLDER
├── sql/                  # SQL templates
│   ├── extract_database.sql
│   ├── extract_schema.sql
│   ├── extract_table.sql
│   ├── extract_column.sql
│   ├── extract_procedure.sql
│   ├── filter_metadata.sql
│   ├── test_authentication.sql
│   └── tables_check.sql
└── generated/            # PKL contract artifacts
    └── manifest.json

tests/
├── unit/                 # 45 unit tests
│   ├── test_mysql_app.py   # MySQLApp class attrs, mappers, hierarchy
│   ├── test_handler.py     # Handler auth, preflight, metadata
│   └── test_clients.py     # SQLClient init, auth types, connection strings
└── e2e/                  # 8 integration tests
    ├── conftest.py         # Testcontainers MySQL + Dapr credential setup
    ├── fixtures/seed.sql   # 5 databases, 99 tables, 1500+ columns
    └── test_mysql_e2e.py   # Handler + workflow + artifact validation

sdr-dev/                  # SDR helm install for dev/test (excluded from image)
├── README.md              # Required env vars + workflow + chart patch notes
├── chart/                 # Patched mysql-app helm chart
├── render.sh              # envsubst wrapper — reads .env, validates
└── values-override.yaml.tmpl  # Templated values; rendered output is gitignored
```

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| **Pre-commit** | All PRs | Ruff lint + format, pyright, isort |
| **Unit Tests** | All PRs | 45 tests, coverage report on PR |
| **Integration Tests** | Push to main, `run-e2e` label | Testcontainers MySQL + Dapr + Temporal |
| **Build Image** | Push to main, tags | Docker build + push to GHCR |

## Makefile Reference

```
make install          # Install deps + download Dapr components
make dev              # Setup creds + start Temporal/Dapr + run app
make test             # Unit tests
make test-cov         # Unit tests with coverage report
make test-e2e         # Integration tests (testcontainers or external MySQL)
make test-e2e-remote  # E2E against deployed vcluster app
make setup-local-creds # Generate Dapr secrets from env vars
make lint             # Ruff linter
make format           # Ruff format + fix
make pre-commit       # Run all pre-commit hooks
make build            # Docker build
make clean            # Remove caches and artifacts

# ── SDR (Self-Deployed Runtime) — see sdr-dev/README.md ──
make sdr-render       # Render sdr-dev/values-override.yaml from .env
make sdr-install      # helm upgrade --install
make sdr-uninstall    # helm uninstall (keeps namespace)
make sdr-teardown     # helm uninstall + delete namespace + remove rendered values
make sdr-status       # Pods + helm status
make sdr-logs         # Tail SDR pod logs
make sdr-port-forward # Port-forward SDR pod :8000 → localhost
```
