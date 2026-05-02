# Changelog

All notable changes to the MySQL App will be documented in this file.

## 0.4.11 (May 2, 2026)

### Bug Fixes

- **Fix publish step receiving empty `connection_qualified_name`**: AE passes `{{connection}}` as a JSON string. `ExtractionInput._normalize_ae_payload` in the SDK did not parse it, so Pydantic fell back to the default empty `ConnectionRef()` — making `input.connection.attributes.qualified_name = ""`. The extract output then had `connection_qualified_name=""`, and the publish step could not link entities to the correct connection. Fixed in `application-sdk@BLDX-968` by JSON-parsing the connection string before Pydantic validation. `uv.lock` updated to pick up the fix.

## 0.4.10 (May 2, 2026)

### Chore

- Version bump to track merged changes from BLDX-1102 (sqltree filters, dag manifest format, workflow_type fix, PKL contract).

## 0.4.9 (May 2, 2026)

### Bug Fixes

- **Fix 500 on workflow submit**: `manifest.json` was using the old `nodes` format — Heracles/AE expects `{"execution_mode": "automation-engine", "dag": {...}}`. Converted to the `dag` format matching the Trino pattern, with `extract` and `publish` nodes and `task_queue: "atlan-mysql-{deployment_name}"`.
- **Fix filter dropdowns**: Switched Include/Exclude Metadata widgets from `apitree` to `sqltree` and added PKL contract (`contract/app.pkl`). See 0.4.8 for details — this bump tracks the manifest fix shipped on top.

## 0.4.8 (May 2, 2026)

### Bug Fixes

- **Fix filter dropdowns not showing schemas**: Changed Include/Exclude Metadata widgets from `apitree` to `sqltree` (matching the legacy Argo configmap and other native connectors like Trino). Renamed workflow params from `include-metadata`/`exclude-metadata` to `include-filter`/`exclude-filter` for consistency. Added `schemaExcludePattern` to hide system schemas (performance_schema, information_schema, mysql, sys) from the picker. Updated `manifest.json` param references accordingly.
- **Add PKL contract** (`contract/app.pkl`): MySQL app now has a typed contract using `Config.SqlTree` for filter widgets, consistent with Trino and other native connectors.
- **Fix 500 on workflow submit**: `manifest.json` was using the old `nodes` format — Heracles/AE expects `{"execution_mode": "automation-engine", "dag": {...}}`. Converted to the `dag` format matching the Trino pattern, with `extract` and `publish` nodes and correct `task_queue: "atlan-mysql-{deployment_name}"`.

## 0.4.7 (May 2, 2026)

### Bug Fixes

- **Fix `fetch_metadata` silently returning empty results when credentials are missing**: `fetch_metadata` now raises explicitly when `host` is absent (turns invisible credential-resolution failures into visible HTTP errors) and propagates exceptions rather than swallowing them — so Heracles returns a non-200 and the frontend can surface the error instead of rendering a blank filter dropdown.

## 0.4.6 (May 1, 2026)

### Bug Fixes

- **`_TABLES_CHECK_SQL` had unresolved placeholders causing preflight SQL failure**: The tables_check.sql template uses `{normalized_exclude_regex}`, `{normalized_include_regex}`, and `{temp_table_regex_sql}` which were not substituted in the handler's `_TABLES_CHECK_SQL` constant. MySQL rejected the literal curly-brace strings as a syntax error. Replaced them with sensible preflight defaults (`^$`, `.*`, empty string).
- **E2E test incorrectly expected HTTP 200 for failed auth**: SDK returns `AuthStatus.FAILED.http_status = 401` for authentication failures (not 200). Updated `test_auth_negative_invalid_auth_type` to assert 401 and verify `data["data"]["status"] == "failed"`.

## 0.4.5 (May 1, 2026)

### Bug Fixes

- **Handler renamed to `MySQLAppHandler` — SDK now discovers it by convention**: SDK auto-discovers a handler named `{AppClass}Handler` in the same module as the App. Our handler was named `MySQLHandler` in a separate file, so the SDK fell back to `DefaultHandler` (which always returns 0 schemas). Renamed to `MySQLAppHandler`, re-exported from `app/mysql.py`, and removed the `ATLAN_HANDLER_MODULE` env var workaround from Dockerfile and `atlan.yaml`. No env var needed — same pattern other v3 apps follow.

## 0.4.4 (May 1, 2026)

### Bug Fixes

- **`ATLAN_HANDLER_MODULE` not set — metadata always returned 0 objects**: The SDK falls back to `DefaultHandler.fetch_metadata` which always returns `SqlMetadataOutput(objects=[])` when no handler module is configured. Added `ATLAN_HANDLER_MODULE: "app.handlers.mysql:MySQLHandler"` to `atlan.yaml` deploy.env so the server loads `MySQLHandler` at startup instead. This fixes the "Include metadata filter" UI returning 0 schemas despite valid credentials.

## 0.4.3 (May 1, 2026)

### Observability

- **`fetch_metadata` diagnostic logging**: Added credential count + sorted-key + host log line and an SQL result type + row count log line on the metadata handler. The previous `logger.error` was dropping tracebacks (no `exc_info`), so silent failures from `client.load` or `client.get_results` were indistinguishable from a genuinely empty query result. Values are never logged — only credential keys — so the change is safe to keep around after debugging.

## 0.4.2 (April 30, 2026)

### Bug Fixes

- **SDK**: Sanitize NaN/Inf/NaT in JSONL output — pandas converts SQL NULLs to NaN which is invalid JSON, publish-app rejects it
- **Tests**: Added JSON serialization safety tests (NaN, Inf, NaT edge cases) — 73 unit tests total

## 0.4.1 (April 30, 2026)

### Bug Fixes

- **SDK**: Use `entities.json` filename for transformed entities (publish-app compatible, was `entities.jsonl`)
- **SDK**: Inject `connectionName` into all entities from connection attributes
- **E2E**: Update artifact validation to match new filename

## 0.4.0 (April 30, 2026)

### New Features

- **Parity with legacy Argo connector**: Asset mappers rewritten to match legacy JSONL structure
- **Parity guard rail tests**: 30+ tests validate entity structure against legacy spec (`parity_spec.json`)
- **Relationship refs**: Schema has `database` ref, Table/View has `atlanSchema` ref, Column has `table`/`view` ref
- **customAttributes**: Table/View include engine, version, row_format, collation; Column includes all SQL metadata
- **View support**: `definition`, `description` fields; views have no `rowCount`/`subType`
- **Column improvements**: `isPrimary`/`isForeign` from constraint_type, `dataType` uppercase, `precision`/`numericScale`

### Bug Fixes

- **tenantId**: Added to all entities (top-level + attributes)
- **qualifiedName**: Includes connection QN prefix (was empty before)
- **Schema**: Added `viewsCount`, `database` relationship ref
- **Table**: Added `isPartitioned`, `partitionCount`, `subType`, `sourceCreatedAt`, `atlanSchema` ref
- **Column**: Added `isPartition`, `isForeign`, `numericScale`, `precision`, `table`/`view` relationship refs

## 0.3.6 (April 30, 2026)

### Bug Fixes

- **SDK**: Fix `connection_qn` resolution — use `connection.attributes.qualified_name` (not `connection.qualified_name`)
- **JSONL**: Add `tenantId` to all entity mappers (database, schema, table, column)
- **qualifiedName**: Now includes connection QN prefix (e.g. `default/mysql/123/def/atlan/table`)
- **connectionQualifiedName**: No longer empty in transformed entities

## 0.3.5 (April 29, 2026)

### Bug Fixes

- **SDK**: Auto-resolve `output_path` via `build_output_path()` in each task (activity context) — same pattern as azure-event-hub. Ensures fetch/transform write parquet/JSONL and upload pushes to S3.
- **Pre-commit**: Move all pyatlan imports to top level in publish integration test

## 0.3.4 (April 29, 2026)

### Bug Fixes

- **SDK**: Auto-set `output_path` from `workflow_id` in workflow context (not activity context) — ensures fetch/transform/upload runs on deployed apps
- **Pre-commit**: Move all pyatlan imports to top level in publish integration test

## 0.3.3 (April 29, 2026)

### Bug Fixes

- **SDK**: Auto-set `output_path` from `build_output_path()` when empty — ensures fetch/transform/upload runs on deployed apps

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
