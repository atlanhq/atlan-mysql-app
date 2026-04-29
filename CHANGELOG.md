# Changelog

All notable changes to the MySQL App will be documented in this file.

## 0.3.2 (April 29, 2026)

### New Features

- **Publish integration**: Full ETL pipeline — E&T COMPLETED + PublishWorkflow COMPLETED
- **Temporal port-forward**: `test-e2e-remote` now port-forwards Temporal internal frontend for publish workflow
- **Connection attributes**: Proper `typeName`/`attributes` structure in workflow payload

### Bug Fixes

- **Cleanup NameError**: Fixed `conn` → `created` in teardown
- **Indexing wait**: Increased to 30s for entity verification after publish

## 0.3.1 (April 29, 2026)

### Bug Fixes

- **Disable split deployment**: `splitDeploymentEnabled: false` — runs handler + worker in single pod (avoids workflow node scheduling issues)

## 0.3.0 (April 29, 2026)

### New Features

- **Publish integration test**: Full ETL pipeline — extract, transform, publish to Atlan, verify entities
- **Unique test connections**: Each test run creates a unique Connection via pyatlan with `uuid` suffix, cleaned up after
- **Entity verification**: Verifies databases, schemas, tables, columns are published to Atlan after PublishWorkflow

## 0.2.3 (April 29, 2026)

### Bug Fixes

- **Remote e2e**: Skip `output_path` for remote tests (pod can't write to local temp dirs)
- **Include filter**: Remove default filter — pass empty string, let SDK/credentials handle it

## 0.2.2 (April 29, 2026)

### Bug Fixes

- **atlan.yaml**: Align with azure-event-hub pattern — `execution_mode` top-level, `self_deployed_runtime: false`, remove explicit resources (use platform defaults)

## 0.2.1 (April 29, 2026)

### Bug Fixes

- **Makefile**: Use Make variables in `test-e2e-remote` instead of shell env vars
- **Pre-commit**: Expand `APP_PATHS` to include Makefile, atlan.yaml, workflows
- **atlan.yaml**: Split deployment with `execution_mode: native`
- **Build workflow**: Versioned GM publish via `release_tag` from `version.txt`
- **CI**: Remove duplicate `build-image.yml`, stale v2 workflows

## 0.2.0 (April 29, 2026)

### New Features

- **v3 SDK migration**: Migrated from v2 to v3 Application SDK extending `SqlApp` template
- **Split deployment**: Handler + Worker as separate pods via `splitDeploymentEnabled: true`
- **Native execution**: Temporal-based orchestration replacing Argo workflows
- **Asset mappers**: Pure Python mappers for databases, schemas, tables, views, columns
- **Testcontainers e2e**: Zero-config integration tests with MySQL 8.0 container + seed data (5 DBs, 99 tables, 1500+ columns)
- **Extraction report**: CI-visible report with entity counts and timings
- **IAM auth**: Support for basic, IAM user, and IAM role authentication

### Bug Fixes

- **AuthOutput**: Use `status=AuthStatus` instead of `success=bool` (v3 contract)
- **PreflightStatus**: Use `NOT_READY` instead of `FAILED` (v3 enum)
- **App name**: Use `name` ClassVar instead of `_app_name` (base class derives from `cls.name`)
- **Handler preflight**: Graceful `load()` error handling
- **IAM connection string**: Correct username in test assertion

### CI/CD

- **Parallel CI**: Pre-commit, unit tests, integration tests run concurrently
- **Testcontainers**: MySQL container with seed data, no secrets needed
- **Ruff PLC0415**: Inline import ban enforced via pre-commit
- **Coverage**: 84%+ threshold with 45 unit tests + 8 e2e tests

## 0.1.0

- Initial MySQL connector with basic auth support
