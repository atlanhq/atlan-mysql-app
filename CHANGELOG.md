# Changelog

All notable changes to the MySQL App will be documented in this file.

## 0.4.50 (May 8, 2026)

### Documentation

- **SDR credential UI form: spell out which value goes in which field**: contributors hit `Access denied for user 'SDR_MYSQL_USERNAME'@…` after pasting `.env` var names (or literal credentials) into the Atlan UI workflow form. The form's Username/Password fields take *bundle keys* (`ATLAN_MYSQL_USERNAME`, `ATLAN_MYSQL_PASSWORD`) — labels the SDK looks up inside the JSON bundle stored in `MYSQL_SECRETS`. [`values-override.yaml.tmpl`](sdr-dev/values-override.yaml.tmpl) and [`sdr-dev/README.md`](sdr-dev/README.md) now spell this out as a table with the exact value to type into each field.

## 0.4.49 (May 8, 2026)

### Bug Fixes

- **SDR install: image repo and pull secret bootstrap**: the chart pointed at Docker Hub (`atlanhq/atlan-mysql-app`) but Atlan's runtime image is published to GHCR. Updated to `ghcr.io/atlanhq/atlan-mysql-app`. Additionally, `make sdr-install` now creates the namespace if missing and copies the `atlan-docker-secret` from `mysql-sdr-imp01` (configurable via `SDR_PULL_SECRET_SRC_NAMESPACE`) so the GHCR pull works end-to-end without manual setup.

## 0.4.48 (May 8, 2026)

### Refactor

- **`SDR_RELEASE_NAME` is now the single source of truth in `.env`** (was `SDR_DEPLOYMENT_NAME`). Contributors set the full helm release name (e.g. `mysql-app-sdr-dev`) and the Atlan-side suffix (`dev`) is derived by stripping the `mysql-app-sdr-` prefix. Avoids the recurring confusion of "is this a suffix or a release name?" — now it's always a release name. The Makefile and `render.sh` both validate the prefix and fail-fast with a clear error if it's missing.
- **`render.sh` standalone is now also conflict-proof**: when invoked directly (without `make sdr-render`) it unsets every `SDR_*` env var found in the shell before sourcing `.env`, matching the Makefile's behavior. Stale shell exports can never override `.env`.

## 0.4.47 (May 8, 2026)

### Bug Fixes

- **`make sdr-*` unsets every `SDR_*` env var before sourcing `.env`**: previously only `SDR_RELEASE_NAME` was unset, so a stale shell value for `SDR_DEPLOYMENT_NAME` (or any other `SDR_*` var) survived when the corresponding line was commented out in `.env`. Now the `SDR_LOAD_ENV` macro enumerates all `SDR_*` vars in the env and unsets them, so a removed/commented line is honored on the next run without restarting the shell.
- **Tighter guard in `render.sh`**: catches both the bare prefix `mysql-app-sdr` and the full release name `mysql-app-sdr-<suffix>` when accidentally set as `SDR_DEPLOYMENT_NAME`. The suggested fix in the error message strips the prefix correctly for both forms.

## 0.4.46 (May 8, 2026)

### Refactor

- **`make sdr-*` targets self-source `.env`**: every SDR target now re-sources the file in a fresh subshell with `SDR_RELEASE_NAME` unset first, so contributors don't need to `source .env` manually between edits and stale shell vars from a prior `source` can't poison the run.
- **Release name pattern: `mysql-app-sdr-{deployment}`** (was `mysql-sdr-{deployment}`). Aligns with the chart name `mysql-app` and makes the SDR-vs-prod distinction explicit. Namespace also moves from `mysql-sdr` → `mysql-app-sdr`. The double-prefix guard in `render.sh` now catches `mysql-app-sdr-*` accidentally pasted into `SDR_DEPLOYMENT_NAME`.
- **`SDR_DEPLOYMENT_NAME` defaults to `dev`** if unset, so a freshly cloned `.env` runs without further config.

## 0.4.45 (May 8, 2026)

### Bug Fixes

- **`render.sh` catches the "full release name in `SDR_DEPLOYMENT_NAME`" mistake**: pasting `mysql-sdr-dev` (the release name) into `SDR_DEPLOYMENT_NAME` instead of just the suffix `dev` produces a double-prefix release `mysql-sdr-mysql-sdr-dev` and a confusing Atlan-side queue. Guard now fails fast with the suggested fix.

## 0.4.44 (May 8, 2026)

### Bug Fixes

- **`make sdr-render` ignores stale `SDR_RELEASE_NAME` in the shell**: a previous `source .env` (when the file still had `SDR_RELEASE_NAME` as an explicit line) would leak the old value into later runs even after the line was removed, because `source` only adds env vars and never removes them. Both the Makefile (now uses `override SDR_RELEASE_NAME := mysql-sdr-$(SDR_DEPLOYMENT_NAME)`) and `sdr-dev/render.sh` (uses `=` instead of `:=` to force-overwrite) now always derive the release name from `SDR_DEPLOYMENT_NAME`. Contributors only manage `SDR_DEPLOYMENT_NAME`.

## 0.4.43 (May 8, 2026)

### Refactor

- **Auto-derive `SDR_RELEASE_NAME` from `SDR_DEPLOYMENT_NAME`**: contributors only set `SDR_DEPLOYMENT_NAME` (the agent suffix / queue tail); release name defaults to `mysql-sdr-${SDR_DEPLOYMENT_NAME}`. Override `SDR_RELEASE_NAME` explicitly only for non-standard cases. `render.sh` substitutes both, `Makefile` derives the same way for `helm uninstall` / `sdr-teardown`.

## 0.4.42 (May 8, 2026)

### Refactor

- **Simpler SDR env vars**: replaces `SDR_DEPLOYMENT_IMAGE` (the combined `repo:tag`) with just `SDR_IMAGE_TAG` — the image repo `atlanhq/atlan-mysql-app` is fixed for this app, so only the tag is worth templating. Avoids the visual collision between `SDR_DEPLOYMENT_NAME` and `SDR_DEPLOYMENT_IMAGE` in `.env`. Also clarifies that `SDR_MYSQL_USERNAME` / `SDR_MYSQL_PASSWORD` are independent of the e2e `MYSQL_*` creds (the SDR pod typically targets a different DB) — `.env.example` shows both the literal-value pattern and the `${MYSQL_USER}` alias pattern.

## 0.4.41 (May 8, 2026)

### Features

- **`make sdr-teardown` for full cluster cleanup**: helm uninstall + delete namespace + remove rendered `values-override.yaml`. Complements the existing `make sdr-uninstall` (helm-only, keeps namespace for fast re-install). Both targets are documented in [README.md](README.md) and [sdr-dev/README.md](sdr-dev/README.md).

## 0.4.40 (May 8, 2026)

### Refactor

- **`SDR_DEPLOYMENT_IMAGE` replaces split `SDR_IMAGE_REPO` + `SDR_IMAGE_TAG`**: contributors now set one combined `repo:tag` env var (e.g. `SDR_DEPLOYMENT_IMAGE=atlanhq/atlan-mysql-app:main-decd72f`) — the natural form pasted from registries / CI builds. `sdr-dev/render.sh` splits it into the two values the chart's `image.repository` / `image.tag` still need, with a clear error when the colon is missing. `.env.example` and `sdr-dev/README.md` updated to match.

## 0.4.39 (May 8, 2026)

### Features

- **In-repo SDR helm install for dev/test (`sdr-dev/`)**: ships a patched copy of the mysql-app helm chart, an `envsubst`-based `render.sh`, and `make sdr-{render,install,uninstall,status,logs,port-forward}` targets so contributors can install the app as a Self-Deployed Runtime against a real tenant without copying YAML between repos. All knobs come from `.env` (`SDR_*` vars added to `.env.example`); the rendered `values-override.yaml` is gitignored. Added a top-level `.dockerignore` that excludes `sdr-dev/`, `tests/`, `local/`, etc. so dev tooling never lands in the runtime image. README updated with a new SDR section + Makefile reference; `sdr-dev/README.md` documents the chart patches (in-cluster Temporal, OAuth disabled, secretstore name) and credential-resolution patterns (multi-key bundle vs single-key).

## 0.4.38 (May 7, 2026)

### Bug Fixes

- **Bump SDK to latest BLDX-968 (`03f01cec`)**: picks up the new single-key per-field secret resolution path on `application_sdk.credentials.agent` (honors `key-type: single-key`), the latest `origin/main` merge into BLDX-968 (contract toolkit move BLDX-1048, IPv4 SDR Temporal/auth pin, `run_dev_combined` env-var fallbacks), and the regenerated SDK capability manifest.

## 0.4.37 (May 7, 2026)

### Bug Fixes

- **Switch SDK pin to consolidated `BLDX-968` branch**: previously pinned to commit `206050c0` (the PR #1690 fix branch). Both [PR #1689](https://github.com/atlanhq/application-sdk/pull/1689) (SDR credential resolution) and [PR #1690](https://github.com/atlanhq/application-sdk/pull/1690) (direct-mode follow-up) have been folded into the parent [BLDX-968 PR #1589](https://github.com/atlanhq/application-sdk/pull/1589) along with a new single-key per-field secret resolution path for `key-type: single-key` agent specs. The mysql-app pin now follows the `BLDX-968` branch directly so future fixes land without re-pinning.

## 0.4.36 (May 7, 2026)

### Bug Fixes

- **Bump application-sdk to pick up SDR credential resolution fix**: `SqlApp._init_sql_client` was skipping credential resolution in SDR mode (`extraction_method = "agent"`) because it only routed through the resolver when `credential_guid` was set. With SDR, only `agent_json` carries the credential payload, so the activity received `creds={}` and every `fetch_*` task failed with `ValueError: username is required`. Fixed in [application-sdk PR #1689](https://github.com/atlanhq/application-sdk/pull/1689) — `_init_sql_client` now routes both direct (credential_guid) and SDR (agent_spec) modes through `CredentialRef.resolve(input)`. SDK pin moves to `48c2a45e` on the `BLDX-968` branch.

## 0.4.35 (May 7, 2026)

### Bug Fixes

- **SDR mode: switch include/exclude/preflight filters to ConditionalInput**: in SDR (`extraction-method = "agent"`) mode the metadata step was emitting `Config.SqlTree` and `Config.SageV2` widgets unchanged, so the UI tried `POST /api/service/credentials/query?app_id=atlan-mysql` to live-browse schemas — that endpoint expects an `authType` field that the agent credential payload doesn't carry, returning `Request body has an error: doesn't match the schema: Property 'authType' is missing`. Mirrored the [atlan-trino-app](https://github.com/atlanhq/atlan-trino-app) and [atlan-cloudsql-postgres-app](https://github.com/atlanhq/atlan-cloudsql-postgres-app) pattern: `include-filter` and `exclude-filter` are now `Config.ConditionalInput` with a `sqltree` base for direct mode and a text-input override (`{"^db$": ["^schema$"]}` JSON regex) for agent mode; `preflight-check` is now `Config.ConditionalInput` that renders the SageV2 checks in direct mode and is hidden in agent mode (the agent has no live DB connection at form time). Fixes the "Please check your credentials and try again" error on the metadata step in SDR.

## 0.4.34 (May 6, 2026)

### Bug Fixes

- **Switch qi / lineage-app / lineage-publish to typed toolkit nodes**: previously declared as raw `DAGNode`s with hand-rolled snake_case args, which bypassed the toolkit's typed mappings. Converted to `QueryIntelligenceNode`, `LineageNode`, and `LineagePublishNode` (matching atlan-trino-app and atlan-cloudsql-postgres-app). The structural fix is the dependency wiring: `lineage-app` now uses `dependsOnCondition` with `andConditions` requiring `tag = "success"` on both `qi` and `publish`, and `lineage-publish` requires `tag = "success"` on `lineage-app` — previously raw `dependsOn { "qi"; "publish" }` only checked node existence, so a failed upstream node didn't block downstream nodes. Storage args: `qi` no longer emits `lake_provider` / `storage_bucket` (QI's worker doesn't read them — confirmed via grep of [atlan-query-intelligence-app](https://github.com/atlanhq/atlan-query-intelligence-app) `app/`; storage backend comes from the `CLOUD` / `S3_BUCKET` env vars Helm injects). `lineage-app` *does* keep `lake_provider: "aws"` and `cloud_storage_bucket: ...` because [atlan-lineage-app](https://github.com/atlanhq/atlan-lineage-app) `app/lib/ingest/artifact_loader.py` actively branches on these to decide between local and cloud artifact loading. Workflow IDs / queues / display names are unchanged.

## 0.4.33 (May 6, 2026)

### Bug Fixes

- **Align SDR contract with Trino / cloudsql-postgres reference apps**: Diffed against latest main of `atlan-trino-app` (`b8bacce`) and `atlan-cloudsql-postgres-app`. The trino dev confirmed the same double-config render appears once SDR is enabled in their contract too, so this fix focuses on contract parity rather than UI behavior. Changes: (1) added `flatManifestArgs = true` and `credentialFieldName = null` to drop the unused `mysql_credential` alias from the generated `AppInputContract`; (2) added the missing `agent` `UIRule` so `anyOf` declares both `direct` and `agent` validation branches (was emitting only `direct`); (3) aligned `extraction-method` with Trino — `baseWidgetType = "radio"`, `placeholderText`, `validationRules`, "Self-Deployed Runtime" label, and Direct/SDR clarification helpText. Generated `mysql.json` is now structurally identical to `trino.json` for the credential step.

## 0.4.32 (May 6, 2026)

### Bug Fixes

- **Restore SDR (Self-Deployed Runtime) credential mapping UI**: Earlier we replaced `Config.AgentSelector` with a hidden `Config.TextInput` to suppress what looked like duplicate credential rendering in Direct mode. That removed the agent picker entirely — selecting "Self-Deployed Runtime" showed nothing. Reverted to `Config.AgentSelector` (matching Trino's pattern) with a proper `agentConfig` covering all three auth types (basic, iam_user, iam_role) and their `extra.*` fields. The "second" credential form visible alongside Direct mode is the standard Atlan SDR credential-path mapping UX, used by all dual-mode connectors.

## 0.4.31 (May 6, 2026)

### Bug Fixes

- **Fix IAM User / IAM Role auth via credential form**: Previous attempt added `db_username` (IAM User) and `aws_role_arn` (IAM Role) as top-level fields in the PKL credential form, but the Atlan credential UI silently drops custom top-level fields — only `host`/`port`/`username`/`password`/`extra` are forwarded. Switched to the `extraFields { ... }` block on each `AuthOption`, which renders nested credential fields and serializes them into `extra.*` (matching the legacy Argo MySQL form). Verified payload structure: IAM User now sends `extra.username` (MySQL DB user), IAM Role now sends `extra.aws_role_arn`. Client code reverted to the simpler legacy reads (no top-level fallbacks needed).

## 0.4.30 (May 5, 2026)

### Bug Fixes

- **Fix double credential form rendering in workflow setup**: The PKL `agent-json` field used `Config.AgentSelector` (widget type `agent`), which caused the Atlan UI to render the entire credential form a second time below the direct credentials with "Store Credential Path" placeholders. Removing `agentConfigEntries` didn't help — the second form was triggered by the `agent` widget type itself. Replaced with a hidden `Config.TextInput` so `agent-json` is still passed to the workflow but doesn't trigger the duplicate UI rendering. SDR remains functional via the AE orchestrator populating `agent_json` directly.

## 0.4.29 (May 5, 2026)

### Bug Fixes

- **Fix IAM User auth**: PKL form had wrong field names — `aws_access_key_id`/`aws_secret_access_key` went to `credentials.*` but client reads `credentials["username"]` (access key) and `credentials["password"]` (secret key). Fixed PKL to use `username`/`password` for AWS credentials and `db_username` for the MySQL database user. Client updated to read `db_username` as fallback alongside legacy `extra.username`.
- **Fix IAM Role auth**: PKL stored `aws_role_arn` at `credentials["aws_role_arn"]` but client only checked `extra["aws_role_arn"]`. Client now also checks `credentials.get("aws_role_arn")` as fallback.
- **Fix SDR basic auth**: agent_json passes credentials as `basic.username`/`basic.password` (dot notation). The `load()` method now flattens these to `username`/`password` before passing to the base SQL client.
- **Remove unused `aws_region` field**: Region is auto-extracted from the RDS hostname (e.g. `*.ap-south-1.rds.amazonaws.com`); explicit field was redundant.

## 0.4.28 (May 5, 2026)

### New Features

- **SDR / agent extraction support**: Added `extraction-method` ConditionalInput and `agent-json` AgentSelector to the PKL contract (MSSQL/Teradata pattern). Agent mode shows when the `SECURE_AGENT_EXTRACTION` lab flag is enabled.
- **IAM auth in UI**: Added `iam_user` and `iam_role` auth options to the credential form — code already supported these, now the UI exposes them.
- **Toolkit `0.2.9` → `0.9.0`**: Required for `AgentSelector` and `ConditionalInput` type compatibility; aligns with MSSQL.

## 0.4.25 (May 5, 2026)

### Bug Fixes

- **Fix lineage never working for any connection (missing `connection_cache_enabled` flags)**: The publish-app builds the SQLite connection cache when `connection_cache_enabled: true` and `connection_cache_via_app_enabled: true` are passed to the `publish` node. MySQL was missing both flags — the publish-app never built the SQLite, so `lineage-app` always found an empty catalog (`valid_hash_count: 0`). Added both flags to `publish` and `lineage-publish` nodes, matching the MSSQL pattern. The publish-app now writes `connection-cache/default/mysql/{connection_id}.sqlite` after every run.

## 0.4.24 (May 5, 2026)

### Bug Fixes

- **Fix `valid_hash_count: 0` in lineage-app (root cause: wrong `cache_path` format)**: All working connectors (Redshift, AlloyDB) use a connection-specific SQLite file path e.g. `connection-cache/default/redshift/1776852152.sqlite`. MySQL (and Teradata) used `"connection-cache"` — a directory, not a file path. `build_catalog_cache` can't persist to a directory, so `transform_and_generate` (running in a separate activity) can't find the catalog → `valid_hash_count: 0` regardless of whether Atlas is indexed. Added `connection_cache_path` to `MySQLExtractionOutput` computed as `"connection-cache/{connection_qn}.sqlite"` and wired it to `$.extract.outputs.connection_cache_path` in the manifest.

## 0.4.23 (May 5, 2026)

### Bug Fixes

- **Fix lineage failing on every new workflow run (persistent cache_path)**: `lineage-app` was configured with `cache_path: "connection-cache"` — a generic, non-persistent directory. Each run rebuilt the catalog from Atlas from scratch. For a fresh connection whose entities aren't indexed yet when lineage-app starts, the catalog would be empty. Redshift (and other working connectors) use a **connection-specific, persistent SQLite file** (`connection-cache/default/redshift/1776852152.sqlite`) that persists across runs. Changed MySQL to `cache_path: "$.extract.outputs.connection_qualified_name"`, so the cache is keyed to the connection and reused on the second run. First run remains metadata-only (no lineage) because Atlas needs ~10 minutes to index 1,000+ new entities — second run and all subsequent runs produce lineage correctly.

## 0.4.22 (May 5, 2026)

### Bug Fixes

- **Fix lineage-app catalog resolution: add `defaultCatalogName`/`defaultSchemaName` to view entities**: Lineage-app uses `json_key_mapping.default_catalog: "defaultCatalogName"` to resolve bare view names (e.g. `akshaycat`) to fully-qualified Atlas paths. QI reads this from the input entity's top-level fields and passes it through to `success.json`. View entities previously only had `databaseName`/`schemaName` under `attributes` — not accessible as top-level fields. Added `entity["defaultCatalogName"]` and `entity["defaultSchemaName"]` to view entity output in `map_table()`, making them visible to QI's `column_mapping` pass-through.
- **Root cause of zero lineage (Atlas indexing delay)**: Lineage-app's `build_catalog_cache` ran ~2 minutes after publish for a brand-new connection with 1,227 entities — Atlas search index hadn't caught up yet, so the catalog was empty and all entities were marked `is_temporary: True`. Entities appear in Atlas after ~2 hours. Fix: re-run the workflow after entities are indexed, or submit with an existing connection that already has indexed entities.

## 0.4.21 (May 5, 2026)

### Bug Fixes

- **Fix procedure entities never reaching S3 (SDK bug + upload gap)**: Two separate bugs prevented procedures from being extracted:
  1. **SDK**: `fetch_procedures` wrote parquet to `raw/procedure/` but `transform_procedures` read from `raw/extras-procedure/` — directory name mismatch meant transform always returned 0 records. Fixed in `application-sdk` by aligning the write path to `raw/extras-procedure/`.
  2. **App**: `MySQLApp.run()` calls `super().run()` (which fetches/transforms/uploads standard entities) and then `fetch_procedures` + `transform_procedures`. The standard `upload_to_atlan` runs *before* procedures are fetched, so procedure entities were never uploaded to S3. Added a second `upload_to_atlan` call after `transform_procedures`.

## 0.4.20 (May 5, 2026)

### Bug Fixes

- **Fix NaN leaking as `"nan"` string in table/view customAttributes**: `str(float('nan'))` = `"nan"` bypassed the SDK's `_sanitize_nan` (which only catches float NaN, not the string). Replaced bare `str(val)` calls in `map_table` customAttributes with `_safe_str()`, which converts NaN/Inf → `""` and strips `.0` from whole-number floats (e.g. `"1589248.0"` → `"1589248"` — matching legacy Argo output).
- **Fix `numericScale`/`precision` NaN → None**: `float('nan') or 0` evaluates to `NaN` (NaN is truthy in Python), so the `or 0` guard had no effect — the SDK then sanitized NaN to `None`. Replaced with `_coerce_numeric()` which explicitly checks for NaN/None and returns `0`, matching legacy `0.0` values.
- **Add `sourceCreatedBy` to procedure entities**: `map_procedure()` now sets `sourceCreatedBy` from the DEFINER field (`source_owner`) — matching the legacy Argo connector.

## 0.4.19 (May 5, 2026)

### Bug Fixes

- **Fix lineage-app resolving 0 relationships (view→table)**: MySQL's `information_schema.VIEWS.VIEW_DEFINITION` stores only the SELECT body (no `CREATE VIEW name AS` prefix). QI/gudusoft parsed this as a plain SELECT and correctly detected source tables, but produced `relationships: []` because it couldn't identify the target view. Fixed by prepending `` CREATE VIEW `schema`.`view` AS `` to each view's `definition` field in `map_table()`. With the full CREATE VIEW statement, gudusoft generates Process edges (source table → view), and lineage-app resolves them against the Atlas catalog. Verified by inspecting the QI `success.json` gudusoft output: previously `"relationships": []`, now populated.

## 0.4.18 (May 4, 2026)

### Bug Fixes

- **Fix lineage-app resolving 0 relationships**: `lake_provider: ""` in `manifest.json` caused the lineage-app to default to `"aws"` internally, corrupting its path resolution logic for non-data-lake connectors. Removed `lake_provider` and `cloud_storage_bucket` from both `qi` and `lineage-app` nodes — matching the pattern used by MSSQL and Teradata (JDBC SQL databases that are not data lakes). Cross-referenced against 8 apps in the org to confirm this is the correct config for MySQL.

## 0.4.17 (May 4, 2026)

### Improvements

- **Simplify lineage prefix derivation**: `SqlApp.run()` now exposes `resolved_base` via `ExtractionOutput.output_path`, so `MySQLApp.run()` reads `base_result.output_path` directly instead of calling `workflow.info()` a second time. `workflow.info()` is now called exactly once per extraction run. `TEMPORARY_PATH` import removed from `mysql.py`.

## 0.4.16 (May 4, 2026)

### Bug Fixes

- **Fix `build_output_path()` call in `MySQLApp.run()` for lineage prefixes**: The SDK fix in 0.4.15 corrected `SqlApp.run()`, but `MySQLApp.run()` still called `build_output_path()` to derive `view_lineage_output_prefix` / `lineage_stage_prefix`. Changed to use `workflow.info()` directly. Removed unused `build_output_path` import.

## 0.4.15 (May 4, 2026)

### Bug Fixes

- **Fix "Not in activity context" crash in SqlApp.run()**: `build_output_path()` calls `activity.info()` which is only valid inside a Temporal activity — `SqlApp.run()` is a workflow method. Fixed by using `workflow.info().workflow_id` + `workflow.info().run_id` with `WORKFLOW_OUTPUT_PATH_TEMPLATE` directly. Tests added to `TestRunOutputPrefixes` to prevent regression.

## 0.4.14 (May 4, 2026)

### Bug Fixes

- **Fix incorrect `transformed_data_prefix` sent to publish**: `MySQLExtractionOutput.run()` was computing `base = input.output_path or ""` — AE never sets `input.output_path`, so `get_object_store_prefix("")` returned bare names like `"transformed"` instead of the full S3 key. Fixed at the `SqlApp` base level: `SqlApp.run()` now derives the path from `TEMPORARY_PATH + build_output_path()` (same logic as `_resolve_output_path()`), and `MySQLApp.run()` inherits `transformed_data_prefix` from the base result. `uv.lock` updated to `application-sdk@BLDX-968`.

## 0.4.13 (May 4, 2026)

### New Features

- **Stored procedure extraction**: `MySQLApp.map_procedure()` maps MySQL stored procedures to Atlan `Procedure` entities with `definition` (SQL body) set, writing to `extras-procedure/` — matching the legacy Argo crawler output. `SqlApp.transform_procedures()` task added to SDK.
- **Full lineage pipeline (QI + lineage-app)**: `manifest.json` now has a 5-node DAG mirroring the Athena native app: `extract → qi` (parses view/procedure SQL definitions) and `extract → publish` run in parallel, then `lineage-app` builds `Process`/`ColumnProcess` entities from the QI output, and `lineage-publish` publishes them to Atlas.
- **`MySQLExtractionOutput`**: Extended extract output includes `view_lineage_output_prefix`, `lineage_stage_prefix`, `lineage_publish_state_prefix`, `lineage_current_state_prefix`, and `storage_bucket` so AE's manifest JSONPath expressions resolve correctly for the lineage nodes.

## 0.4.12 (May 3, 2026)

### Bug Fixes

- **Fix publish receiving empty `connection_qualified_name` (root cause)**: `SqlApp.run()` returned `ExtractionOutput` without setting `connection_qualified_name`. The publish workflow reads this via `$.extract.outputs.connection_qualified_name` to derive state prefixes — with it empty, diff compare returned 0 entities and nothing was published. Fixed in `application-sdk@BLDX-968` (`bdb17b78`) by extracting `input.connection.attributes.qualified_name` and setting it on the output, matching the existing pattern in `SqlMetadataExtractor.run()`. `uv.lock` updated.

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
