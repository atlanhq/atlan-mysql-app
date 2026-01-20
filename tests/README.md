# Testing Guide

## Test Structure

- **Unit Tests** (`tests/unit/`): Fast, isolated tests with mocked dependencies
- **E2E Tests** (`tests/e2e/`): Full workflow tests requiring Dapr, Temporal, and database

## Running Tests

### Unit Tests
```bash
uv run pytest tests/unit -v
uv run coverage run -m pytest tests/unit
uv run coverage report
```

### E2E Tests

**Prerequisites:**
1. Start Dapr and Temporal: `uv run poe start-deps`
2. Start app: `uv run main.py`
3. Set environment variables if needed

**Run:**
```bash
uv run pytest tests/e2e -v
```

## Test Files

**Unit Tests:**
- `test_clients.py` - Client authentication tests (basic + IAM)
- `test_workflow.py` - Workflow logic tests
- `transformers/query/` - Transformer validation tests

**E2E Tests:**
- `test_mysql_workflow/` - Basic workflow
