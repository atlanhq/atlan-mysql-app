# Enhancement SPEC: MySQL `clonedInformationSchema`

> **Date:** 2026-04-24
> **Status:** DRAFT
> **Source repo:** `atlanhq/atlan-mysql-app`
> **Reference implementation:** `atlanhq/atlan-redshift-app` (see `similar-patterns.md`)

---

## Enhancement Summary

Add `clonedInformationSchema` config to the MySQL connector, enabling metadata extraction from a user-created mirror schema when direct `information_schema` access is restricted.

---

## Current State (Reference)

The MySQL connector currently hardcodes `information_schema.` as a schema prefix in all metadata extraction SQL. There are **18 `information_schema.` table references** (FROM/JOIN clauses) across **7 SQL files**, plus **2 Python handler SQL attributes** that load from these files via the SDK.

### Affected Files -- Current Hardcoded References

| File | Line(s) | Table(s) Referenced | Count |
|------|---------|---------------------|:-----:|
| `app/sql/extract_column.sql` | 63, 64, 78, 79, 95, 96, 131, 133 | `KEY_COLUMN_USAGE`, `TABLE_CONSTRAINTS` (x3 each), `COLUMNS`, `TABLES` | 8 |
| `app/sql/extract_table.sql` | 30, 70, 78, 81 | `COLUMNS`, `TABLES`, `PARTITIONS`, `VIEWS` | 4 |
| `app/sql/extract_schema.sql` | 24, 31 | `SCHEMATA`, `TABLES` | 2 |
| `app/sql/extract_procedure.sql` | 31 | `ROUTINES` | 1 |
| `app/sql/filter_metadata.sql` | 18 | `SCHEMATA` | 1 |
| `app/sql/tables_check.sql` | 18 | `TABLES` | 1 |
| `app/sql/extract_database.sql` | 22 | `SCHEMATA` | 1 |
| **Total** | | | **18** |

### Python Handler References

| File | Attribute | Description |
|------|-----------|-------------|
| `app/handlers/mysql.py:34` | `metadata_sql` | SDK's `BaseSQLHandler.metadata_sql` processed through `_replace_database_placeholder()` |
| `app/handlers/mysql.py:35` | `tables_check_sql` | SDK's `BaseSQLHandler.tables_check_sql` processed through `_replace_database_placeholder()` |

### Python Activities References

| File | Attribute | Description |
|------|-----------|-------------|
| `app/activities/metadata_extraction/mysql.py:45` | `fetch_database_sql` | Class attribute from SDK base |
| `app/activities/metadata_extraction/mysql.py:48` | `fetch_schema_sql` | Class attribute from SDK base |
| `app/activities/metadata_extraction/mysql.py:51` | `fetch_table_sql` | Class attribute from SDK base |
| `app/activities/metadata_extraction/mysql.py:54` | `fetch_column_sql` | Class attribute from SDK base |
| `app/activities/metadata_extraction/mysql.py:57` | `fetch_procedure_sql` | Class attribute from SDK base |

### Unique `information_schema` Tables Used

| Table | Used In |
|-------|---------|
| `SCHEMATA` | `extract_schema.sql`, `filter_metadata.sql`, `extract_database.sql` |
| `TABLES` | `extract_table.sql`, `extract_schema.sql`, `tables_check.sql`, `extract_column.sql` |
| `COLUMNS` | `extract_table.sql`, `extract_column.sql` |
| `VIEWS` | `extract_table.sql` |
| `PARTITIONS` | `extract_table.sql` |
| `ROUTINES` | `extract_procedure.sql` |
| `KEY_COLUMN_USAGE` | `extract_column.sql` |
| `TABLE_CONSTRAINTS` | `extract_column.sql` |

**8 unique `information_schema` tables** must be mirrored in any cloned schema.

---

## What Changes (PRD Spec Checks)

### PRD-MYSQL-CLONE-001: SQL Placeholder Replacement

**Scope:** All 18 `information_schema.` references across 7 SQL files.

**Change:** Replace every `information_schema.` prefix with `{cloned_information_schema}` placeholder.

**Before:**
```sql
FROM information_schema.TABLES T
```

**After:**
```sql
FROM {cloned_information_schema}TABLES T
```

**Key design decision:** The placeholder includes the trailing dot when resolved. Default value is `"information_schema."` (not empty string). This differs from Redshift where the default is `""` because Redshift implicitly resolves `pg_catalog` tables without a prefix, but MySQL requires the explicit `information_schema.` prefix.

**Files to modify:**

| File | Lines to Change |
|------|----------------|
| `app/sql/extract_column.sql` | 63, 64, 78, 79, 95, 96, 131, 133 |
| `app/sql/extract_table.sql` | 30, 70, 78, 81 |
| `app/sql/extract_schema.sql` | 24, 31 |
| `app/sql/extract_procedure.sql` | 31 |
| `app/sql/filter_metadata.sql` | 18 |
| `app/sql/tables_check.sql` | 18 |
| `app/sql/extract_database.sql` | 22 |

**Acceptance criteria:**
- [ ] All 18 references replaced with `{cloned_information_schema}` placeholder
- [ ] `grep -c 'information_schema\.' app/sql/*.sql` returns 0 for FROM/JOIN references (comments/NOT IN lists excluded)
- [ ] Default resolution produces identical SQL to current hardcoded form

---

### PRD-MYSQL-CLONE-002: `resolve_cloned_information_schema()` Utility

**Scope:** New file `app/activities/metadata_extraction/utils.py`

**Change:** Create a utility function modeled on Redshift's `resolve_cloned_sql()`.

**Signature:**
```python
def resolve_cloned_information_schema(
    workflow_args: Dict[str, Any],
    default_sql: Optional[str],
) -> Optional[str]:
```

**Behavior:**

1. If `default_sql` is `None` or empty, return `None`.
2. Read `workflow_args["control-config-strategy"]`.
3. If strategy is `"custom"` and `workflow_args["control-config"]` exists:
   - Parse `control-config` (handle both `dict` and JSON string).
   - Extract `"clonedInformationSchema"` value.
   - If set, build prefix: `f"{cloned_schema}."` (e.g., `"atlan_meta."`).
4. If no cloned schema configured, use default prefix: `"information_schema."`.
5. Replace `{cloned_information_schema}` in `default_sql` with the resolved prefix.
6. Return resolved SQL.

**Critical difference from Redshift:** The default is `"information_schema."` not `""`.

**Acceptance criteria:**
- [ ] Function exists with documented signature
- [ ] Returns `None` for `None`/empty input
- [ ] Returns SQL with `information_schema.` prefix when no config is set
- [ ] Returns SQL with custom prefix when `clonedInformationSchema` is configured
- [ ] Handles `control-config` as both string and dict
- [ ] Gracefully handles malformed JSON in `control-config`

---

### PRD-MYSQL-CLONE-003: Custom Control Config UI Wiring

**Scope:** `app/templates/workflow.json`

**Change:** Add `advanced-config`, `control-config-strategy`, and `control-config` properties to the workflow JSON, following the Redshift pattern.

**New properties to add:**

```json
"advanced-config": {
    "type": "string",
    "enum": ["default", "custom"],
    "default": "default",
    "required": true,
    "enumNames": ["Default", "Advanced"],
    "ui": {
        "widget": "radio",
        "hidden": false,
        "label": "Advanced Config",
        "help": "Set advanced configuration of the crawler"
    }
},
"control-config-strategy": {
    "type": "string",
    "enum": ["default", "custom"],
    "default": "default",
    "required": true,
    "enumNames": ["Default", "Custom"],
    "ui": {
        "widget": "radio",
        "hidden": false,
        "label": "Control Config",
        "help": "Controls custom experimental feature flags for the crawler"
    }
},
"control-config": {
    "type": "string",
    "ui": {
        "label": "Custom Config",
        "help": "Custom JSON config controlling experimental feature flags. Example: {\"clonedInformationSchema\": \"atlan_meta\"}",
        "placeholder": "{\"clonedInformationSchema\": \"atlan_meta\"}",
        "hidden": false,
        "default": "{}"
    }
}
```

**Conditional visibility (anyOf additions):**

```json
{
    "properties": {
        "advanced-config": { "const": "custom" }
    },
    "required": ["control-config-strategy"]
},
{
    "properties": {
        "advanced-config": { "const": "custom" },
        "control-config-strategy": { "const": "custom" }
    },
    "required": ["control-config"]
}
```

**Step placement:** Add `advanced-config`, `control-config-strategy`, and `control-config` to the `"metadata"` step properties.

**Acceptance criteria:**
- [ ] `advanced-config` radio appears in Metadata step
- [ ] `control-config-strategy` appears only when Advanced is selected
- [ ] `control-config` text field appears only when Control Config is Custom
- [ ] Default state shows none of these fields (existing UX unchanged)
- [ ] No existing workflow.json fields are modified

---

### PRD-MYSQL-CLONE-004: NOT IN Exclusion List Update

**Scope:** All SQL files containing `NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')`.

**Change:** When a cloned schema is configured, add the cloned schema name to the exclusion list so it does not appear as a user schema in extraction results.

**Approach option A -- Dynamic SQL injection:**

The `resolve_cloned_information_schema()` function also replaces a `{cloned_schema_exclusion}` placeholder:
- Default: empty string (no additional exclusion needed since `information_schema` is already excluded)
- With clone: `', '<cloned_schema_name>'` (appended inside the NOT IN list)

**Before:**
```sql
WHERE T.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys'{cloned_schema_exclusion})
```

**After (with clone `atlan_meta`):**
```sql
WHERE T.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys', 'atlan_meta')
```

**Files affected:**
- `app/sql/extract_column.sql` (line 135)
- `app/sql/extract_table.sql` (line 82)
- `app/sql/extract_schema.sql` (line 36)
- `app/sql/extract_procedure.sql` (line 32)
- `app/sql/filter_metadata.sql` (line 19)
- `app/sql/tables_check.sql` (line 21)
- `app/sql/extract_database.sql` (line 23)

**Acceptance criteria:**
- [ ] Cloned schema name is excluded from metadata results
- [ ] Default behavior (no clone) produces identical SQL to current
- [ ] The original `information_schema` remains in the exclusion list regardless

---

### PRD-MYSQL-CLONE-005: Handler SQL Update

**Scope:** `app/handlers/mysql.py`

**Change:** Apply `resolve_cloned_information_schema()` to `metadata_sql` and `tables_check_sql`.

The handler SQL attributes come from the SDK base class and are currently only processed through `_replace_database_placeholder()`. They also need the information_schema placeholder treatment.

**Implementation:** Chain the resolution:

```python
class MySQLHandler(BaseSQLHandler):
    metadata_sql = _replace_database_placeholder(BaseSQLHandler.metadata_sql)
    tables_check_sql = _replace_database_placeholder(BaseSQLHandler.tables_check_sql)
```

Since the handler does not have access to `workflow_args` at class definition time, the resolution must happen at runtime. The handler's `metadata_sql` and `tables_check_sql` need to have their `information_schema.` references replaced with `{cloned_information_schema}` placeholders at class level, and then resolved at runtime when `workflow_args` is available.

**Acceptance criteria:**
- [ ] Handler `metadata_sql` contains `{cloned_information_schema}` placeholder
- [ ] Handler `tables_check_sql` contains `{cloned_information_schema}` placeholder
- [ ] Resolution happens at runtime with access to `workflow_args`
- [ ] Default behavior unchanged

---

### PRD-MYSQL-CLONE-006: Activities SQL Update

**Scope:** `app/activities/metadata_extraction/mysql.py`

**Change:** Apply `resolve_cloned_information_schema()` to all `fetch_*_sql` class attributes at activity execution time, following the Redshift pattern.

**Current class attributes affected:**
- `fetch_database_sql` (line 45)
- `fetch_schema_sql` (line 48)
- `fetch_table_sql` (line 51)
- `fetch_column_sql` (line 54)
- `fetch_procedure_sql` (line 57)

**Implementation pattern** (following Redshift's `redshift.py`):

```python
@activity.defn
@auto_heartbeater
async def fetch_tables(self, workflow_args):
    self.fetch_table_sql = resolve_cloned_information_schema(
        workflow_args=workflow_args,
        default_sql=self.fetch_table_sql,
    )
    return await super().fetch_tables(workflow_args)
```

Apply the same override pattern for `fetch_schemas`, `fetch_columns`, `fetch_databases`, and `fetch_procedures`.

**Acceptance criteria:**
- [ ] All 5 `fetch_*_sql` attributes are resolved through `resolve_cloned_information_schema()`
- [ ] Resolution happens before SQL execution (in the activity method, before calling super)
- [ ] Activities import from `app.activities.metadata_extraction.utils`
- [ ] Default behavior produces identical SQL to current

---

### PRD-MYSQL-CLONE-007: DBA Setup Script

**Scope:** New documentation artifact (SQL script).

**Change:** Provide a DBA-ready SQL script that creates a mirror schema containing views (or tables) for all 8 required `INFORMATION_SCHEMA` tables.

**Script outline:**

```sql
-- Create mirror schema
CREATE SCHEMA IF NOT EXISTS atlan_meta;

-- Create views mirroring INFORMATION_SCHEMA tables
CREATE OR REPLACE VIEW atlan_meta.SCHEMATA AS
    SELECT * FROM information_schema.SCHEMATA;

CREATE OR REPLACE VIEW atlan_meta.TABLES AS
    SELECT * FROM information_schema.TABLES;

CREATE OR REPLACE VIEW atlan_meta.COLUMNS AS
    SELECT * FROM information_schema.COLUMNS;

CREATE OR REPLACE VIEW atlan_meta.VIEWS AS
    SELECT * FROM information_schema.VIEWS;

CREATE OR REPLACE VIEW atlan_meta.PARTITIONS AS
    SELECT * FROM information_schema.PARTITIONS;

CREATE OR REPLACE VIEW atlan_meta.ROUTINES AS
    SELECT * FROM information_schema.ROUTINES;

CREATE OR REPLACE VIEW atlan_meta.KEY_COLUMN_USAGE AS
    SELECT * FROM information_schema.KEY_COLUMN_USAGE;

CREATE OR REPLACE VIEW atlan_meta.TABLE_CONSTRAINTS AS
    SELECT * FROM information_schema.TABLE_CONSTRAINTS;

-- Grant access to Atlan user
GRANT SELECT ON atlan_meta.* TO 'atlan_user'@'%';
```

**Note:** MySQL's `information_schema` tables are actually virtual tables generated at query time. Whether views or materialized copies are used depends on the customer's MySQL version and access restrictions. The script should document both approaches.

**Acceptance criteria:**
- [ ] Script covers all 8 `information_schema` tables used by the connector
- [ ] Script includes GRANT statements
- [ ] Script is tested against MySQL 8.0+
- [ ] Documentation notes that views provide live data (no refresh needed), unlike Redshift's table-copy approach

---

### PRD-MYSQL-CLONE-008: Backward Compatibility

**Scope:** All changes above.

**Constraints:**

1. **Default behavior MUST remain identical** when `clonedInformationSchema` is not set:
   - All SQL resolves to `information_schema.TABLE_NAME` (current form)
   - No new fields visible in workflow UI (existing users see no change)
   - No changes to credential config
   - No changes to API endpoints

2. **No changes to workflow.json existing fields:**
   - `credential-guid`, `include-metadata`, `exclude-metadata`, `exclude-table-regex`, `preflight-check` -- all unchanged
   - New fields are additive only

3. **No changes to extraction logic beyond schema references:**
   - All transform logic unchanged
   - All asset types unchanged
   - All output contracts unchanged

**Acceptance criteria:**
- [ ] Existing workflow configs (without advanced settings) produce identical behavior
- [ ] Round-trip test: run extraction with default config, compare output to pre-change baseline
- [ ] No new required fields in workflow.json

---

### PRD-MYSQL-CLONE-009: Documentation

**Scope:** Customer-facing docs in `atlan-docs`.

**Change:** Add documentation for MySQL cloned schema setup, following the Redshift docs pattern.

**Documentation deliverables:**

1. **Setup guide section** in MySQL setup docs (`set-up-mysql.mdx` or equivalent):
   - "Cloned schema for restricted access" heading
   - DBA steps to create the mirror schema
   - Grant statements
   - Note about view-based vs. table-based approach

2. **Crawler configuration guide** section:
   - How to enter the cloned schema name in the Advanced Config
   - JSON format: `{"clonedInformationSchema": "<schema_name>"}`
   - Screenshot or description of the UI flow

**Acceptance criteria:**
- [ ] Setup guide covers the mirror schema creation
- [ ] Configuration guide covers the UI workflow
- [ ] Both docs follow existing Redshift docs pattern and style
- [ ] No placeholder credentials in examples (use `<schema_name>`, `atlan_user`, etc.)

---

### PRD-MYSQL-CLONE-010: Live Validation

**Scope:** Integration testing.

**Change:** Validate the full feature against a live MySQL instance.

**Test scenarios:**

| Test | Config | Expected Result |
|------|--------|-----------------|
| Default extraction (no clone) | No `control-config` | Identical output to pre-change baseline |
| Clone extraction | `{"clonedInformationSchema": "atlan_meta"}` | Extraction succeeds using mirror schema |
| Invalid clone schema | `{"clonedInformationSchema": "nonexistent"}` | SQL error (schema not found), not silent failure |
| Empty control-config | `control-config-strategy: "custom"`, `control-config: "{}"` | Falls back to `information_schema` (default) |
| Malformed JSON | `control-config: "not json"` | Falls back to `information_schema` (default, graceful degradation) |
| Exclusion list | Clone schema `atlan_meta` | `atlan_meta` does NOT appear as a user schema in results |

**Acceptance criteria:**
- [ ] All 6 test scenarios pass
- [ ] Extraction output (schemas, tables, columns, procedures) matches expected asset counts
- [ ] No regressions in existing test suite

---

## Backward Compatibility Constraints

| Constraint | Enforcement |
|-----------|-------------|
| Default behavior MUST remain identical when `clonedInformationSchema` is not set | `resolve_cloned_information_schema()` defaults to `"information_schema."` |
| No changes to workflow.json existing fields | New fields are additive; existing `anyOf` entries untouched |
| No changes to credential config | `clonedInformationSchema` is in `control-config`, not credentials |
| No changes to API endpoints | Feature is config-driven, no new endpoints |
| No changes to extraction logic beyond schema references | Only string replacement in SQL; all downstream logic untouched |

---

## What Stays the Same

- All extraction logic beyond schema references (query execution, pagination, file writing)
- All transform logic (`MySQLQueryBasedTransformer`, YAML templates)
- All asset types (Database, Schema, Table, View, Column, Procedure)
- All output contracts (JSON structure, field names, file layout)
- All credential handling (MySQL auth, connection config)
- `_replace_database_placeholder()` function and `DATABASE_PLACEHOLDER` constant
- `app/sql/client_version.sql`, `app/sql/test_authentication.sql` (no `information_schema` references)
- `app/sql/extract_temp_table_regex_column.sql`, `app/sql/extract_temp_table_regex_table.sql` (no `information_schema` references)

---

## Implementation Order (Suggested)

1. **PRD-MYSQL-CLONE-002** -- Create `resolve_cloned_information_schema()` utility (foundation)
2. **PRD-MYSQL-CLONE-001** -- Replace all 18 SQL hardcoded references with placeholders
3. **PRD-MYSQL-CLONE-004** -- Add `{cloned_schema_exclusion}` to NOT IN lists
4. **PRD-MYSQL-CLONE-006** -- Wire activities to call resolution utility
5. **PRD-MYSQL-CLONE-005** -- Wire handler SQL to use placeholders
6. **PRD-MYSQL-CLONE-003** -- Add UI config to workflow.json
7. **PRD-MYSQL-CLONE-008** -- Verify backward compatibility (test default path)
8. **PRD-MYSQL-CLONE-007** -- Write DBA setup script
9. **PRD-MYSQL-CLONE-009** -- Write documentation
10. **PRD-MYSQL-CLONE-010** -- Live validation

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| MySQL does not allow creating views on `information_schema` in some managed environments (e.g., RDS restrictions) | Medium | High | Document alternative: `CREATE TABLE ... AS SELECT` with cron refresh, similar to Redshift pattern |
| Placeholder replacement breaks SQL syntax if placeholder appears in string literals or comments | Low | High | Audit all SQL files to confirm placeholder only appears in FROM/JOIN clauses; add regression tests |
| Handler SQL comes from SDK base class and may not contain `information_schema.` references | Low | Medium | Verify SDK base class SQL content; handle case where placeholder is absent gracefully |
| `control-config` JSON parsing fails silently | Low | Medium | Log warning on parse failure; fall back to default `information_schema.` prefix |
