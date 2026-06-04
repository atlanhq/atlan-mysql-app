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
make test        # runs the full unit suite
make test-cov    # with HTML coverage report
```

Coverage threshold is enforced by `pytest-cov` via `[tool.coverage.report].fail_under` in `pyproject.toml` (currently `84`). Auto-generated files under `app/generated/**` are excluded via `[tool.coverage.run].omit` since they're regenerated from `contract/app.pkl` and have no value being tested. If you lower the threshold, do so deliberately — the SDK's Certify-app publish gate runs the same `pytest --cov` and a coverage failure exits the unit-tests step non-zero, which blocks marketplace publish.

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
├── unit/                 # unit suite (auth, mappers, handlers, parity, etc.)
│   ├── test_mysql_app.py   # MySQLApp class attrs, mappers, hierarchy
│   ├── test_handler.py     # Handler auth, preflight, metadata
│   └── test_clients.py     # SQLClient init, auth types, connection strings
└── e2e/                  # integration tests
    ├── conftest.py         # Testcontainers MySQL + Dapr credential setup
    ├── fixtures/seed.sql   # 5 databases, 99 tables, 1500+ columns
    └── test_mysql_e2e.py   # Handler + workflow + artifact validation

```

## Contract & Codegen

The app's metadata (connector form, manifest, channel/segment config, secret schemas) is **generated** from `contract/app.pkl` by the [App Contract Toolkit](https://github.com/atlanhq/application-sdk). The committed `app/generated/` directory is the output of that codegen — never edit it by hand.

### When to regenerate

Run `uv run poe generate` after editing `contract/app.pkl` or bumping the toolkit version in `contract/PklProject`. The task is defined in `pyproject.toml`:

```toml
[tool.poe.tasks]
generate = "bash -c 'cd contract && pkl eval -m generated app.pkl && cp generated/app/generated/*.json ../app/generated/ && rm -rf generated'"
```

Then commit the resulting changes under `app/generated/`.

### Why this matters for publish

The SDK Certify-app gate (in the Build & Publish workflow) runs `poe generate` and then `git diff --exit-code` to ensure the committed output is current. If `poe generate` errors or leaves a dirty working tree, **publish is blocked**. Two failure modes to know about:

- **`Unrecognized task 'generate'`** — `pyproject.toml` is missing the task. Required by every connector app shipped through the SDK Certify gate.
- **`generated/ is stale`** — `contract/app.pkl` was changed but `app/generated/` wasn't regenerated. Run `uv run poe generate` and commit.

## Release & Publish

The repo uses a **label-driven** release flow wired up by three workflows:

| Workflow | Trigger | Role |
|----------|---------|------|
| `release.yaml` | manual or scheduled | Calls SDK's `release-version-bump.yaml` — opens an auto bump PR with the `release` label |
| `release-gate.yaml` | every PR | Blocks merge of any PR labeled `release` until a reviewer also adds the `e2e` label |
| `tag-and-publish.yaml` | PR merged to `main` with `release` label | Creates the git tag + GitHub Release, which then fires `build-and-publish.yaml` with `publish=true` and runs the full Certify → Build → Push → Marketplace chain |

### How to cut a new version

1. **Bump PR is opened** by the version-bump workflow (auto-labels `release`).
2. **Reviewer adds `e2e`** to the bump PR — this is the explicit opt-in to run the full e2e suite as the final gate. Without it, `Release Gate` fails by design.
3. **Wait for `Tests / tests-passed` to be green** (unit + e2e). Force-pushes to the bump branch cancel in-flight runs; just rerun if needed.
4. **Merge the PR.** GitHub fires `pull_request.closed` → `tag-and-publish.yaml` creates the tag + Release → `release.types[published]` → `build-and-publish.yaml` runs with `publish=true`.

### What "publish=true" actually controls

The wrapper at `.github/workflows/build-and-publish.yaml` resolves the flag:

```yaml
publish: ${{ github.event_name == 'release' || inputs.publish == true }}
```

So `publish=true` happens **automatically** on a GitHub Release event, or **manually** via `gh workflow run build-and-publish.yaml -f publish=true`. When false, Certify-app, Credential leak gate, Validate Channel + Branch, and Publish-to-Marketplace are all skipped by design — that's why a normal push-to-`main` Build & Publish run shows several jobs in a "skipped" state. They're not failing, they're gated.

### Common publish failures

| Symptom | Cause | Fix |
|---|---|---|
| `Unrecognized task 'generate'` in Certify-app | `pyproject.toml` missing the `generate` poe task | Add the task (see Contract & Codegen above) |
| `Coverage failure: total of N is less than fail-under=M` | Coverage below threshold | Add tests, or update `[tool.coverage.run].omit` if newly-generated files are dragging it down, or adjust `fail_under` |
| `Release PR requires the 'e2e' label` | `release-gate.yaml` blocks unlabeled release PRs | Reviewer adds the `e2e` label |
| Certification verdict fails despite unit tests passing | One of `check_migration`, `contract_drift`, or `coverage_threshold` was warn-only but `unit` tests failed (which IS blocking) | Inspect the Certify-app step summary on the failing run |

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| **Pre-commit** | All PRs | Ruff lint + format, pyright |
| **Tests** | All PRs, push to main | Unit + integration tests; `tests-passed` is the required check |
| **Release Gate** | All PRs | Passes immediately for non-release PRs; blocks `release`-labeled PRs until `e2e` label is added |
| **Build & Publish** | Push to main, `release.types[published]`, `workflow_dispatch` | Build + scan + dispatch deploy; on `release` events also Certify + Marketplace publish |
| **Tag and Publish** | PR `closed` with `release` label | Creates git tag + GitHub Release — the trigger for the publish chain |
| **Vulnerability Scan** | All PRs | Trivy + Snyk + Socket security checks |

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
```
