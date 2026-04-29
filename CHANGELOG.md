# Changelog

All notable changes to the MySQL App will be documented in this file.

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
