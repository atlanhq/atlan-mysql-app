# Testing Guide

## Test Structure

| Directory | What it tests | CI job |
|---|---|---|
| `tests/unit/` | Fast, isolated tests with mocked dependencies | `tests` (every PR) |
| `tests/integration/` | Full workflow via testcontainers MySQL (no external creds) | `tests` (every PR) |
| `tests/e2e/` | Full system-apps DAG against a real tenant (extract→qi→publish→lineage) | `e2e` (`e2e` label or dispatch) |

## Running Tests Locally

### Unit + Integration (no external services needed beyond Docker)
```bash
uv run python -m app.run_dev &    # start the app (embedded Temporal + in-process backends)
uv run pytest tests/unit/ tests/integration/ -v
```

### E2E (full-DAG, requires tenant credentials)
```bash
ATLAN_BASE_URL=https://devex.atlan.com \
ATLAN_API_KEY=... \
SDR_OAUTH_CLIENT_ID=... SDR_OAUTH_CLIENT_SECRET=... \
GITHUB_RUN_ID=$(date +%s) \
    uv run pytest tests/e2e/ -v
```
