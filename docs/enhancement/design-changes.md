# Design Changes: MySQL `clonedInformationSchema`

> **Date:** 2026-04-24
> **Status:** DRAFT — pending human approval (contracts frozen after approval)
> **Trigger:** REQ-925
> **Reference:** Enhancement SPEC (`enhancement-spec.md`)

---

## 1. Summary

Add a `clonedInformationSchema` config option to the MySQL connector. When configured, all SQL queries use a customer-provided mirror schema instead of `information_schema.*`. When not configured, behavior is identical to today.

**Scope:** 7 SQL files modified, 1 new utility file, 1 workflow.json update, 5 activity method overrides, 2 handler SQL attributes updated, 1 DBA setup script added.

---

## 2. New Files

### `app/activities/metadata_extraction/utils.py`

New utility module containing `resolve_cloned_information_schema()`.

```python
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INFORMATION_SCHEMA_PREFIX = "information_schema."


def resolve_cloned_information_schema(
    workflow_args: Dict[str, Any],
    default_sql: Optional[str],
) -> Optional[str]:
    """Resolve {cloned_information_schema} placeholders in SQL.

    Reads 'control-config-strategy' and 'control-config' from workflow_args.
    If a 'clonedInformationSchema' key is configured, replaces the placeholder
    with '<schema_name>.'. Otherwise defaults to 'information_schema.'.

    Also resolves {cloned_schema_exclusion} for NOT IN list additions.

    Args:
        workflow_args: Workflow arguments dict containing config.
        default_sql: SQL template string with placeholders.

    Returns:
        Resolved SQL string, or None if default_sql is None/empty.
    """
    if not default_sql:
        return None

    info_schema_prefix = DEFAULT_INFORMATION_SCHEMA_PREFIX
    schema_exclusion = ""

    control_config_strategy = workflow_args.get("control-config-strategy")
    control_config = workflow_args.get("control-config")

    if control_config_strategy == "custom" and control_config:
        if isinstance(control_config, str):
            try:
                control_config = json.loads(control_config)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse control-config JSON, using default information_schema"
                )
                control_config = {}

        cloned_schema = (control_config or {}).get("clonedInformationSchema")
        if cloned_schema:
            info_schema_prefix = f"{cloned_schema}."
            schema_exclusion = f", '{cloned_schema}'"

    resolved = default_sql.replace(
        "{cloned_information_schema}", info_schema_prefix
    )
    resolved = resolved.replace("{cloned_schema_exclusion}", schema_exclusion)
    return resolved
```

### `scripts/create_mirror_schema.sql`

DBA setup script for creating the mirror schema. See PRD-MYSQL-CLONE-007 in SPEC.

```sql
-- =============================================================
-- Atlan MySQL Connector: Mirror Schema Setup Script
-- =============================================================
-- Purpose: Create a mirror schema for INFORMATION_SCHEMA tables
--          when direct INFORMATION_SCHEMA access is restricted.
--
-- Usage:   Replace 'atlan_meta' with your desired schema name.
--          Replace 'atlan_user' with the Atlan service account.
--
-- Note:    MySQL views on INFORMATION_SCHEMA provide live data —
--          no refresh/cron needed (unlike Redshift's table-copy approach).
--          The executing user must have SELECT on INFORMATION_SCHEMA.
-- =============================================================

-- 1. Create mirror schema
CREATE SCHEMA IF NOT EXISTS atlan_meta;

-- 2. Create views mirroring required INFORMATION_SCHEMA tables
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

-- 3. Grant SELECT on mirror schema to Atlan service account
GRANT SELECT ON atlan_meta.* TO 'atlan_user'@'%';

-- 4. Verify setup
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'atlan_meta'
ORDER BY TABLE_NAME;
```

---

## 3. Modified Files — SQL Placeholders

### Pattern

Every `information_schema.` in FROM/JOIN clauses → `{cloned_information_schema}`

Every NOT IN system schema list gets `{cloned_schema_exclusion}` appended.

### `app/sql/extract_database.sql`

**Changes:** 1 placeholder + 1 exclusion

```
- FROM information_schema.SCHEMATA
+ FROM {cloned_information_schema}SCHEMATA

- NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys')
+ NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys'{cloned_schema_exclusion})
```

### `app/sql/extract_schema.sql`

**Changes:** 2 placeholders + 1 exclusion

```
- FROM information_schema.SCHEMATA S
+ FROM {cloned_information_schema}SCHEMATA S

- FROM information_schema.TABLES
+ FROM {cloned_information_schema}TABLES

- NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys')
+ NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys'{cloned_schema_exclusion})
```

### `app/sql/extract_table.sql`

**Changes:** 4 placeholders + 1 exclusion

```
- FROM information_schema.COLUMNS C
+ FROM {cloned_information_schema}COLUMNS C

- FROM information_schema.TABLES T
+ FROM {cloned_information_schema}TABLES T

- FROM information_schema.PARTITIONS
+ FROM {cloned_information_schema}PARTITIONS

- LEFT JOIN information_schema.VIEWS V
+ LEFT JOIN {cloned_information_schema}VIEWS V

- NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys')
+ NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys'{cloned_schema_exclusion})
```

### `app/sql/extract_column.sql`

**Changes:** 8 placeholders + 1 exclusion

All `information_schema.KEY_COLUMN_USAGE` (x3), `information_schema.TABLE_CONSTRAINTS` (x3), `information_schema.COLUMNS` (x1), `information_schema.TABLES` (x1) → `{cloned_information_schema}` prefix.

```
- NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys')
+ NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys'{cloned_schema_exclusion})
```

### `app/sql/extract_procedure.sql`

**Changes:** 1 placeholder + 1 exclusion

```
- FROM information_schema.ROUTINES R
+ FROM {cloned_information_schema}ROUTINES R
```

### `app/sql/filter_metadata.sql`

**Changes:** 1 placeholder + 1 exclusion

```
- FROM information_schema.SCHEMATA S
+ FROM {cloned_information_schema}SCHEMATA S
```

### `app/sql/tables_check.sql`

**Changes:** 1 placeholder + 1 exclusion

```
- FROM information_schema.TABLES T
+ FROM {cloned_information_schema}TABLES T
```

---

## 4. Modified Files — Python

### `app/activities/metadata_extraction/mysql.py`

**Changes:** Add 5 `@activity.defn` method overrides to resolve placeholders at runtime.

```python
from app.activities.metadata_extraction.utils import resolve_cloned_information_schema

class MySQLSQLMetadataExtractionActivities(BaseSQLMetadataExtractionActivities):
    # ... existing class attributes unchanged ...

    @activity.defn
    @auto_heartbeater
    async def fetch_databases(self, workflow_args: Dict[str, Any]) -> ActivityStatistics:
        self.fetch_database_sql = resolve_cloned_information_schema(
            workflow_args=workflow_args,
            default_sql=self.fetch_database_sql,
        )
        return await super().fetch_databases(workflow_args)

    @activity.defn
    @auto_heartbeater
    async def fetch_schemas(self, workflow_args: Dict[str, Any]) -> ActivityStatistics:
        self.fetch_schema_sql = resolve_cloned_information_schema(
            workflow_args=workflow_args,
            default_sql=self.fetch_schema_sql,
        )
        return await super().fetch_schemas(workflow_args)

    @activity.defn
    @auto_heartbeater
    async def fetch_tables(self, workflow_args: Dict[str, Any]) -> ActivityStatistics:
        self.fetch_table_sql = resolve_cloned_information_schema(
            workflow_args=workflow_args,
            default_sql=self.fetch_table_sql,
        )
        return await super().fetch_tables(workflow_args)

    @activity.defn
    @auto_heartbeater
    async def fetch_columns(self, workflow_args: Dict[str, Any]) -> ActivityStatistics:
        self.fetch_column_sql = resolve_cloned_information_schema(
            workflow_args=workflow_args,
            default_sql=self.fetch_column_sql,
        )
        return await super().fetch_columns(workflow_args)

    @activity.defn
    @auto_heartbeater
    async def fetch_procedures(self, workflow_args: Dict[str, Any]) -> ActivityStatistics:
        self.fetch_procedure_sql = resolve_cloned_information_schema(
            workflow_args=workflow_args,
            default_sql=self.fetch_procedure_sql,
        )
        return await super().fetch_procedures(workflow_args)
```

### `app/handlers/mysql.py`

**Changes:** Handler SQL attributes need `{cloned_information_schema}` placeholders inserted at class level. The handler's `prepare_metadata()` and `preflight_check()` methods receive `workflow_args` at runtime — override them to resolve before calling super.

```python
from app.activities.metadata_extraction.utils import resolve_cloned_information_schema

class MySQLHandler(BaseSQLHandler):
    metadata_sql = _replace_database_placeholder(BaseSQLHandler.metadata_sql)
    tables_check_sql = _replace_database_placeholder(BaseSQLHandler.tables_check_sql)

    # Add placeholder insertion for information_schema references
    if metadata_sql:
        metadata_sql = metadata_sql.replace(
            "information_schema.", "{cloned_information_schema}"
        )
    if tables_check_sql:
        tables_check_sql = tables_check_sql.replace(
            "information_schema.", "{cloned_information_schema}"
        )

    async def prepare_metadata(self, workflow_args=None, **kwargs):
        if workflow_args:
            self.metadata_sql = resolve_cloned_information_schema(
                workflow_args=workflow_args,
                default_sql=self.__class__.metadata_sql,
            )
        return await super().prepare_metadata(workflow_args=workflow_args, **kwargs)

    async def preflight_check(self, workflow_args=None, **kwargs):
        if workflow_args:
            self.tables_check_sql = resolve_cloned_information_schema(
                workflow_args=workflow_args,
                default_sql=self.__class__.tables_check_sql,
            )
        return await super().preflight_check(workflow_args=workflow_args, **kwargs)
```

### `app/templates/workflow.json`

**Changes:** Add 3 new properties and update metadata step. No existing fields modified.

New properties added to `config.properties`:

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
        "help": "Controls custom feature flags for the crawler"
    }
},
"control-config": {
    "type": "string",
    "ui": {
        "label": "Custom Config",
        "help": "Custom JSON config. Example: {\"clonedInformationSchema\": \"atlan_meta\"}",
        "placeholder": "{\"clonedInformationSchema\": \"atlan_meta\"}",
        "hidden": false,
        "default": "{}"
    }
}
```

Metadata step updated:
```json
{
    "id": "metadata",
    "title": "Metadata",
    "description": "Metadata Filters",
    "properties": [
        "include-metadata",
        "exclude-metadata",
        "exclude-table-regex",
        "advanced-config",
        "control-config-strategy",
        "control-config",
        "preflight-check"
    ]
}
```

Conditional visibility via `anyOf`:
```json
"anyOf": [
    {
        "properties": { "advanced-config": { "const": "default" } }
    },
    {
        "properties": { "advanced-config": { "const": "custom" } },
        "required": ["control-config-strategy"]
    },
    {
        "properties": {
            "advanced-config": { "const": "custom" },
            "control-config-strategy": { "const": "custom" }
        },
        "required": ["control-config"]
    }
]
```

---

## 5. Implementation Order

1. `app/activities/metadata_extraction/utils.py` — foundation utility
2. All 7 SQL files — placeholder insertion
3. `app/activities/metadata_extraction/mysql.py` — activity overrides
4. `app/handlers/mysql.py` — handler overrides
5. `app/templates/workflow.json` — UI config
6. `scripts/create_mirror_schema.sql` — DBA script
7. Unit tests
8. Integration tests with live MySQL

---

## 6. Risks

| Risk | Mitigation |
|------|-----------|
| Handler SQL comes from SDK base class — may change in SDK updates | Pin SDK version; re-verify after SDK upgrades |
| `{cloned_information_schema}` placeholder conflicts with other placeholders | Unique name, no overlap with `{database_placeholder}` |
| `prepare_metadata()` / `preflight_check()` signature may differ from base | Verify SDK base class signatures before implementation |
| Views on `information_schema` may not work in all MySQL managed services | Document alternative (CREATE TABLE AS SELECT + cron) |

---

## 7. What Does NOT Change

- `app/clients/__init__.py` — no changes
- `app/transformers/` — no changes
- `app/constants.py` — no changes (DATABASE_PLACEHOLDER stays)
- `app/sql/test_authentication.sql` — no information_schema refs
- `app/sql/client_version.sql` — no information_schema refs
- `app/sql/extract_temp_table_regex_*.sql` — no information_schema refs
- `app/templates/atlan-connectors-mysql.json` — no changes
- All existing contracts and output formats
- All existing tests (must continue passing)
