# MySQL Connector (`atlan-mysql-app`) — Current-State Assessment

## Enhancement Context

Adding a `clonedInformationSchema` config option to allow customers to point metadata extraction at a custom mirror schema instead of `information_schema.*` directly, following the Redshift `clonedPgCatalogSchema` precedent.

---

## 1. File Tree

```
atlan-mysql-app/
├── main.py                          # Application entrypoint
├── pyproject.toml                   # Dependencies & build config
├── atlan.yaml                       # Marketplace/deploy manifest
├── Dockerfile
├── app/
│   ├── constants.py                 # DATABASE_PLACEHOLDER = "def"
│   ├── clients/__init__.py          # SQLClient (AsyncBaseSQLClient)
│   ├── handlers/mysql.py            # MySQLHandler (BaseSQLHandler)
│   ├── activities/metadata_extraction/mysql.py  # MySQLSQLMetadataExtractionActivities
│   ├── transformers/query/
│   │   ├── __init__.py              # MySQLQueryBasedTransformer
│   │   └── sql_query_templates/     # YAML transform templates
│   ├── sql/                         # SQL query files (7 with information_schema refs)
│   │   ├── extract_database.sql
│   │   ├── extract_schema.sql
│   │   ├── extract_table.sql
│   │   ├── extract_column.sql
│   │   ├── extract_procedure.sql
│   │   ├── filter_metadata.sql
│   │   ├── tables_check.sql
│   │   ├── test_authentication.sql  # No info_schema refs
│   │   ├── client_version.sql       # No info_schema refs
│   │   ├── extract_temp_table_regex_table.sql   # No info_schema refs
│   │   └── extract_temp_table_regex_column.sql  # No info_schema refs
│   └── templates/
│       ├── workflow.json            # Workflow UI config
│       └── atlan-connectors-mysql.json  # Credential config
├── tests/
│   ├── unit/
│   │   ├── test_workflow.py         # 4 test functions
│   │   ├── test_clients.py          # 12 test functions
│   │   └── transformers/query/
│   │       ├── test_sql_transformer.py               # 12 test functions
│   │       └── test_sql_transformer_output_validation.py  # 1 golden-file test
│   └── e2e/test_mysql_workflow/     # 6 E2E test functions
└── frontend/static/                 # Pre-built Nuxt.js SPA
```

## 2. App Classes + @task Methods

### SQLClient (`app/clients/__init__.py`)
- Extends: `AsyncBaseSQLClient`
- Methods: `load(credentials)`, `get_iam_user_token()`, `get_iam_role_token()`, `_create_ssl_context()`, `_extract_region_from_hostname()`
- No @task/@activity.defn methods

### MySQLHandler (`app/handlers/mysql.py`)
- Extends: `BaseSQLHandler`
- Class-level SQL: `metadata_sql` (filter_metadata.sql), `tables_check_sql` (tables_check.sql)
- Methods: `__init__()`, `get_configmap()` (static)
- Has `_replace_database_placeholder()` function

### MySQLSQLMetadataExtractionActivities (`app/activities/metadata_extraction/mysql.py`)
- Extends: `BaseSQLMetadataExtractionActivities`
- Class-level SQL: `fetch_database_sql`, `fetch_schema_sql`, `fetch_table_sql`, `fetch_column_sql`, `fetch_procedure_sql`
- **@activity.defn override**: `transform_data()` — splits table/view output
- Has `_replace_database_placeholder()` function (duplicate of handler's)

### MySQLQueryBasedTransformer (`app/transformers/query/__init__.py`)
- Extends: `QueryBasedTransformer`
- Overrides: `prepare_template_and_attributes()` — fixes connection_qualified_name, casts Null columns

## 3. Contracts

No local typed contracts. All types from SDK:
- `DatabaseConfig` — connection string template
- `ActivityStatistics` — activity return type
- `BaseSQLMetadataExtractionActivitiesState` — activity state
- Workflow args: Dict-based (credentials, metadata, connection)

## 4. Handler Endpoints

| Endpoint | Purpose | MySQL Override |
|----------|---------|---------------|
| POST /auth | Test connection | Inherited |
| POST /metadata | Schema list for UI filter | `metadata_sql` replaced |
| POST /check | Preflight: schema, table count, version | `tables_check_sql` replaced |
| GET /configmap/{id} | Frontend config JSON | Fully overridden |
| Workflow activities | Temporal extraction pipeline | `transform_data` overridden |

## 5. SQL Query Inventory — CRITICAL

### information_schema.* Reference Count by File

| SQL File | Tables Referenced | Occurrences |
|----------|------------------|-------------|
| extract_database.sql | SCHEMATA | 1 |
| extract_schema.sql | SCHEMATA, TABLES | 2 |
| extract_table.sql | TABLES, COLUMNS, PARTITIONS, VIEWS | 4 |
| extract_column.sql | COLUMNS, TABLES, KEY_COLUMN_USAGE, TABLE_CONSTRAINTS | 8 |
| extract_procedure.sql | ROUTINES | 1 |
| filter_metadata.sql | SCHEMATA | 1 |
| tables_check.sql | TABLES | 1 |
| **TOTAL** | | **18 occurrences** |

**Pattern**: All references use exact string `information_schema.` (lowercase, trailing dot).

**Important**: `'information_schema'` also appears in NOT IN clauses (system schema exclusion). These are filter VALUES and should NOT be replaced — but the cloned schema name should be ADDED to these exclusion lists.

## 6. Test Inventory

| File | Tests | Type |
|------|-------|------|
| test_workflow.py | 4 functions | Unit (mocked Temporal) |
| test_clients.py | 12 functions | Unit (mocked engine) |
| test_sql_transformer.py | 12 functions | Unit (mocked YAML) |
| test_sql_transformer_output_validation.py | 1 golden-file test | Unit (real transform) |
| test_mysql_workflow.py | 6 functions | E2E (live MySQL) |
| **Total** | **35 test functions** | |

## 7. SDK Version

**v2 (Application SDK 2.1.1)** — pinned to git commit `931c538f`.

App entrypoint pattern: `BaseSQLMetadataExtractionApplication` → `BaseSQLMetadataExtractionWorkflow` → custom activities/handler/client/transformer.

## 8. Backward-Compat Surface

Must NOT change:
- **workflow.json** properties: connection, credential-guid, include-metadata, exclude-metadata, exclude-table-regex, preflight-check
- **atlan-connectors-mysql.json** credential fields: host, port, database, auth-type, basic/iam_user/iam_role nested objects
- **Environment variables**: ATLAN_APP_HTTP_PORT, ATLAN_APPLICATION_NAME, etc.
- **API endpoints**: /auth, /metadata, /check, /workflows/v1/*, /configmap/*
- **Workflow args contract**: credentials, metadata, connection dict structure

## 9. Dependencies

| Dependency | Version | Enhancement Relevant? |
|------------|---------|----------------------|
| atlan-application-sdk | ==2.1.1 | **YES** — provides base classes, read_sql_files(), prepare_query() |
| aiomysql | >=0.2.0 | No |
| jinja2 | >=3.1.2 | Maybe — not used for SQL currently |
| cryptography | >=3.4.0 | No |

## 10. Known Issues

- **DRY violation**: `_replace_database_placeholder()` duplicated in handler and activities
- **Dockerfile uses `:latest`** — should be pinned
- **Architecture doc**: Refers to "PostgreSQL" in places (copy-paste artifact)
- **Skipped test**: `test_mysql_client_connection_string_with_hypothesis` — Hypothesis failures

---

## Redshift Reference Pattern

### How `clonedPgCatalogSchema` Works

| Component | Redshift | MySQL (proposed) |
|-----------|----------|-----------------|
| Config key | `clonedPgCatalogSchema` | `clonedInformationSchema` |
| SQL placeholder | `{cloned_schema}` | `{cloned_information_schema}` |
| Default value | `pg_catalog` | `information_schema` |
| Utility function | `resolve_cloned_sql()` | Similar utility needed |
| Total replacements | ~11 tables | 18 occurrences across 7 files |

### Key Design Consideration

MySQL's `'information_schema'` appears in NOT IN exclusion clauses. The cloned schema name should be added to these exclusion lists to prevent the mirror schema from appearing in results.
