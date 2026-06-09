# MySQL Application

[![Tests](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/tests.yaml/badge.svg)](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/tests.yaml)
[![Build](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/build-and-publish.yaml/badge.svg)](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/build-and-publish.yaml)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

MySQL metadata extraction app built on [Atlan Application SDK v3](https://github.com/atlanhq/application-sdk). Extracts databases, schemas, tables, views, columns, and procedures from MySQL and transforms them into Atlan-compatible assets.

## Architecture

```
MySQLApp(SqlApp)                    MySQLAppHandler(Handler)
├── fetch_databases  @task          ├── test_auth        → AuthOutput
├── fetch_schemas    @task          ├── preflight_check  → PreflightOutput
├── fetch_tables     @task          └── fetch_metadata   → SqlMetadataOutput
├── fetch_columns    @task
├── fetch_procedures @task
├── transform_*      @task  (asset mappers → JSONL)
└── upload_to_atlan  @task
```

- **`app/mysql.py`** — `MySQLApp` extends `SqlApp` with MySQL-specific SQL queries and asset mappers (`map_database`, `map_schema`, `map_table`, `map_column`, `map_procedure`)
- **`app/handlers/mysql.py`** — `MySQLAppHandler` (v3) for auth, preflight, and metadata endpoints
- **`app/clients/`** — `SQLClient` with basic, IAM user, and IAM role authentication
- **`app/sql/`** — SQL templates for metadata extraction
- **`app/run_dev.py`** — local dev entry point (embedded Dapr + Temporal via `run_dev_combined`)
- **`app/generated/`** — PKL-generated contract artifacts (`manifest.json`, `mysql.json`, `atlan-connectors-mysql.json`, `_input.py`, `_e2e_base.py`, `_e2e_credential.py`)

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
- Docker (optional, for testcontainers-based integration tests)

> No standalone Dapr or Temporal CLI install is needed for local dev — the SDK's embedded dev mode boots both in-process and downloads `daprd` into `~/.cache/atlan-sdk/` on first run.

### Setup

```bash
git clone https://github.com/atlanhq/atlan-mysql-app.git
cd atlan-mysql-app
uv sync --all-extras
```

### Local Development

Create a `.env` with your MySQL credentials:

```bash
export MYSQL_HOST="localhost"
export MYSQL_PORT="3306"
export MYSQL_USER="root"
export MYSQL_PASSWORD=""
```

Start the app via the SDK's embedded dev runner — in-process Temporal + in-process backends for state, secrets, and object storage (see `app/run_dev.py`):

```bash
source .env && uv run python -m app.run_dev
# or equivalently:
source .env && uv run python main.py
```

The app is available at `http://localhost:8000`.

> Production / container deployments don't use `main.py` at all — the v3 base image launches the SDK's CLI with `ATLAN_APP_MODULE=app.mysql:MySQLApp` (see `Dockerfile` and `atlan.yaml` → `deploy.env`), which goes through `application_sdk.main:run_combined_mode` with the real Dapr-backed stores.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/server/health` | GET | Health check |
| `/workflows/v1/auth` | POST | Test MySQL connectivity |
| `/workflows/v1/check` | POST | Preflight checks (auth + table access) |
| `/workflows/v1/metadata` | POST | Fetch schema list for UI |
| `/workflows/v1/configmaps` | GET | List configmaps |
| `/workflows/v1/manifest` | GET | App manifest |
| `/workflows/v1/input-contract` | GET | JSON schema for workflow input |
| `/workflows/v1/start` | POST | Start extraction workflow |
| `/workflows/v1/stop/{wf_id}/{run_id}` | POST | Stop a running workflow |
| `/workflows/v1/result/{wf_id}` | GET | Get workflow result |
| `/workflows/v1/status/{wf_id}/{run_id}` | GET | Check workflow status |

## Testing

### Unit Tests (`tests/unit/`)

96 tests covering `MySQLApp` mappers, `MySQLAppHandler`, `SQLClient` auth flows, and asset-parity contracts:

```bash
uv run pytest tests/unit/ -v
uv run pytest tests/unit/ --cov=app --cov-report=term-missing --cov-report=html  # with coverage
```

### Integration Tests (`tests/integration/`)

Handler + workflow tests against a real MySQL via testcontainers (zero config) or an external MySQL via env vars (see `tests/integration/README.md`):

```bash
# With Docker (testcontainers spins up MySQL + seeds 5 DBs / 99 tables / 1500+ columns)
uv run pytest tests/integration/ -v --timeout=600

# With external MySQL
source .env && uv run pytest tests/integration/ -v --timeout=600
```

Validates handler endpoints, full workflow start → poll → COMPLETED, extracted parquet artifacts, transformed JSONL (correct `typeName`, `qualifiedName`, `connectorName`), and the extraction report.

### Full-DAG E2E (`tests/e2e/`)

End-to-end run of the full system-apps DAG (extract → qi → publish → lineage) against a real Atlan tenant. Gated behind the `e2e` PR label or `workflow_dispatch`:

```bash
ATLAN_BASE_URL=https://devex.atlan.com \
ATLAN_API_KEY=... \
SDR_OAUTH_CLIENT_ID=... SDR_OAUTH_CLIENT_SECRET=... \
GITHUB_RUN_ID=$(date +%s) \
  uv run pytest tests/e2e/ -v
```

## Project Structure

```
app/
├── mysql.py              # MySQLApp — SqlApp subclass with SQL queries + asset mappers
├── handlers/mysql.py     # MySQLAppHandler — auth, preflight, metadata
├── clients/__init__.py   # SQLClient — basic + IAM user + IAM role auth
├── constants.py          # DATABASE_PLACEHOLDER
├── failures.py           # Typed failure helpers
├── run_dev.py            # Local dev entry (embedded Dapr + Temporal)
├── sql/                  # SQL templates
│   ├── client_version.sql
│   ├── extract_database.sql
│   ├── extract_schema.sql
│   ├── extract_table.sql
│   ├── extract_column.sql
│   ├── extract_procedure.sql
│   ├── extract_temp_table_regex_table.sql
│   ├── extract_temp_table_regex_column.sql
│   ├── filter_metadata.sql
│   ├── tables_check.sql
│   └── test_authentication.sql
└── generated/            # PKL-generated contract artifacts (do not edit)
    ├── manifest.json
    ├── mysql.json
    ├── atlan-connectors-mysql.json
    ├── _input.py
    ├── _e2e_base.py
    └── _e2e_credential.py

tests/
├── unit/                       # Fast, isolated tests with mocked deps
│   ├── test_mysql_app.py       # MySQLApp class attrs, mappers, hierarchy
│   ├── test_handler.py         # Handler auth, preflight, metadata
│   ├── test_clients.py         # SQLClient init, auth types, connection strings
│   └── test_parity.py          # Asset-parity contracts (DB/schema/table/column)
├── integration/                # Real MySQL via testcontainers or external host
│   ├── conftest.py             # Testcontainers MySQL + credential setup
│   ├── fixtures/seed.sql       # 5 databases, 99 tables, 1500+ columns
│   ├── fixtures/parity_spec.json
│   ├── test_mysql_handler.py
│   ├── test_mysql_workflow.py
│   └── test_credential_resolution.py
└── e2e/                        # Full-DAG against a real tenant
    └── test_mysql_full_dag.py
```

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| **Pre-commit Checks** | All PRs | Ruff lint + format, pyright |
| **Tests** | All PRs, push to main | Unit + integration (testcontainers); `e2e` label runs the full DAG against a real tenant |
| **Build & Publish** | Push to main, releases | Docker build + push to GHCR + marketplace publish |
| **Vulnerability Scan** | All PRs | Dependency + image CVE scan |
| **Dep Cooldown** | All PRs | Blocks dep bumps younger than the org threshold |
| **Docstring Coverage** | All PRs | Enforces docstring coverage of `app/` |
| **Conventional Commits** | All PRs | Validates PR title format |
| **Autolabel** | All PRs | Labels PRs from conventional-commit prefix |
| **Release Gate** | Release-bump PRs | Requires `e2e` label before merge |
| **Release Version Bump** | Merge to main | Opens a version-bump PR |
| **Release and Publish** | Merge of release-labeled PR | Tags + creates GitHub release |
| **Update Security Dashboard** | After scans | Pushes results to security dashboard |
| **Weekly Dependency Update** | Mon 07:00 UTC | Opens a dep-upgrade PR if anything changed |

## Common Commands

```bash
uv sync --all-extras                                # Install deps
uv run python -m app.run_dev                        # Run app locally (embedded Temporal + in-process backends)
uv run pytest tests/unit/ -v                        # Unit tests
uv run pytest tests/integration/ -v --timeout=600   # Integration tests (testcontainers)
uv run pytest tests/e2e/ -v --timeout=600           # Full-DAG E2E (requires tenant creds)
uv run ruff check app/ tests/                       # Lint
uv run ruff format app/ tests/                      # Format
uv run pre-commit run --all-files                   # All pre-commit hooks
uv run poe generate                                 # Regenerate PKL contract artifacts
uv run poe download-components                      # Download Dapr components (production parity)
docker build -t atlan-mysql-app:latest .            # Build image
```
