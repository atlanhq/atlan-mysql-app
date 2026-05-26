# Parity Tests

Compares **v2 (golden baseline)** against **v3 (new version)** output to ensure the v3 MySQL connector produces identical results.

> Templated from atlan-mssql-app. The integration scenario class
> `TestMySQLIntegration` (under `tests/integration/test_mysql_integration.py`)
> must be ported before parity runs end-to-end.

## Three Layers of Testing

### 1. Data Parity (`test_parity.py`)

Compares the actual transformed metadata output (databases, schemas, tables, columns, procedures):

- **Record counts** — v3 must extract the same number of records per entity type
- **Coverage** — every v2 asset must appear in v3 (by `qualifiedName`), and no extra v3 assets
- **Attribute parity** — every attribute on every record must match (with loose comparison for counts like `rowCount`, and null/empty equivalence)
- **TypeName match** — Atlas type names must be identical

### 2. API Contract Parity (`test_contract_parity.py`)

Compares the structure of API responses (`/auth`, `/check`, `/metadata`, `/start`, `/status`, `/result`):

- **Key presence** — all keys in v2 responses must exist in v3
- **Type matching** — value types must match (int/float interchangeable, None allowed)
- **Handler contracts** — v3 responses have required fields (e.g., `success`, `workflow_id`, `status`)

### 3. Performance Parity (`test_performance_parity.py`)

- **Wall clock time** — v3 must complete within `2x` of v2 (configurable via `PARITY_DURATION_MULTIPLIER`)
- **Execution duration** — same threshold
- **Record counts match** — extracted record counts must be identical
- Generates a comparison report table

## How It Runs

The orchestrator is `run_parity.py`. It:

1. **Discovers scenarios** from `tests/integration/test_mysql_integration.py` — each scenario provides workflow args, credentials, and API type
2. **Runs v2 workflow** against a live v2 instance (default `localhost:3000`) — POSTs `/start`, polls `/status`, reads transformed output from disk
3. **Normalizes v2 output** — replaces connection QNs with a canonical placeholder, strips volatile fields (`lastSyncRun`, etc.), sorts by `qualifiedName` — saves as `golden/*.jsonl`
4. **Records v2 API responses** — calls all handler endpoints, normalizes (replaces UUIDs, timestamps), saves to `api_golden/*.json`
5. **Repeats steps 2-4 for v3** (default `localhost:8000`), saving to `v3/` and `api_v3/`
6. **Runs pytest** on all three test files to compare

## Directory Structure

```
tests/parity/
├── output/              # Gitignored — all scenario output goes here
│   └── <scenario_name>/
│       ├── golden/          # v2 normalized output (baseline)
│       │   ├── database.jsonl
│       │   ├── schema.jsonl
│       │   ├── table.jsonl
│       │   ├── column.jsonl
│       │   ├── procedure.jsonl
│       │   └── view.jsonl
│       ├── v3/              # v3 normalized output
│       │   └── ... (same files)
│       ├── api_golden/      # v2 API response snapshots
│       │   ├── auth.json
│       │   ├── check.json
│       │   ├── metadata.json
│       │   ├── start.json
│       │   ├── status.json
│       │   ├── result.json
│       │   └── timing.json
│       └── api_v3/          # v3 API response snapshots
│           └── ... (same files)
├── .gitignore           # Ignores output/
├── api_recorder.py      # Records and normalizes API responses
├── conftest.py          # Loads .env credentials
├── run_parity.py        # Orchestrator
├── test_parity.py       # Data parity tests
├── test_contract_parity.py   # API contract tests
└── test_performance_parity.py # Performance tests
```

## Usage

```bash
# Full run (v2 golden + v3 + compare):
uv run python tests/parity/run_parity.py

# Only generate v2 golden:
uv run python tests/parity/run_parity.py --v2-only

# Only generate v3 output (golden must exist):
uv run python tests/parity/run_parity.py --v3-only

# Single scenario:
uv run python tests/parity/run_parity.py --scenario empty_filters

# Custom hosts:
uv run python tests/parity/run_parity.py --v2-host http://localhost:3000 --v3-host http://localhost:8000

# Just generate outputs, skip pytest:
uv run python tests/parity/run_parity.py --no-test

# Run comparison only (if outputs already exist):
uv run pytest tests/parity/ -v
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PARITY_DURATION_MULTIPLIER` | `2.0` | Max allowed v3/v2 duration ratio |
| `PARITY_V3_OUTPUT` | — | Override v3 output path (fallback for manual runs) |

## Normalization

Both v2 and v3 output go through normalization before comparison:

- **Connection QNs** are replaced with `default/mysql/__PARITY__`
- **Volatile fields** (`lastSyncWorkflowName`, `lastSyncRun`, `lastSyncRunAt`) are stripped
- **API responses** have UUIDs, timestamps, and duration values replaced with placeholders
- Records are sorted by `qualifiedName` for stable comparison
