# Similar Patterns: Redshift `clonedPgCatalogSchema` Deep-Dive

> **Date:** 2026-04-24
> **Source repo:** `atlanhq/atlan-redshift-app`
> **Purpose:** Reference implementation for MySQL `clonedInformationSchema` feature

---

## 1. `resolve_cloned_sql()` Function

**File:** `app/activities/metadata_extraction/utils.py`

### Function Signature

```python
def resolve_cloned_sql(
    workflow_args: Dict[str, Any],
    default_sql: Optional[str],
    cloned_sql_template: Optional[str] = None,  # Deprecated. Ignored.
) -> Optional[str]:
```

### How It Reads the Config

The function follows a **two-step gating** pattern:

1. **Strategy check:** Reads `workflow_args["control-config-strategy"]`. Only proceeds if the value is `"custom"`.
2. **Config extraction:** Reads `workflow_args["control-config"]`. If the value is a JSON string, it is parsed with `json.loads()`. The cloned schema name is extracted from the key `"clonedPgCatalogSchema"`.

```python
control_config_strategy = workflow_args.get("control-config-strategy")
control_config = workflow_args.get("control-config")

cloned_schema_prefix = ""

if control_config_strategy == "custom" and control_config:
    if isinstance(control_config, str):
        try:
            import json
            control_config = json.loads(control_config)
        except Exception:
            control_config = {}

    cloned_schema = (control_config or {}).get("clonedPgCatalogSchema")
    if cloned_schema:
        cloned_schema_prefix = f"{cloned_schema}."
```

### How It Performs the Replacement

The function uses simple string replacement on the SQL template:

```python
sql = default_sql.replace("{cloned_schema}", cloned_schema_prefix)
if database_name:
    sql = sql.replace("{database_name}", str(database_name))
return sql
```

The `{cloned_schema}` placeholder is placed **directly before** table names (no dot separator in the placeholder itself). When a cloned schema is configured, the replacement value includes the trailing dot (e.g., `"atlan."`). When no cloned schema is configured, the replacement is an empty string `""`.

**Example transformations:**

| Config | Template | Result |
|--------|----------|--------|
| `clonedPgCatalogSchema: "atlan"` | `FROM {cloned_schema}svv_tables` | `FROM atlan.svv_tables` |
| (no config / default strategy) | `FROM {cloned_schema}svv_tables` | `FROM svv_tables` |

### Default Behavior (No Config)

When `control-config-strategy` is not `"custom"` or `control-config` is empty/absent:
- `cloned_schema_prefix` remains `""`
- All `{cloned_schema}` placeholders are replaced with empty string
- SQL queries resolve to their standard system catalog form (e.g., `pg_namespace`, `svv_tables`)
- **No behavioral change from pre-feature behavior**

### Additional: `{database_name}` Resolution

The function also resolves `{database_name}` from credentials:

```python
credentials: Dict[str, Any] = workflow_args.get("credentials", {}) or {}
database_name = credentials.get("database") or (
    credentials.get("extra", {}) or {}
).get("database")
```

---

## 2. SQL Files Using `{cloned_schema}` Placeholder

### Files with placeholder (3 of 17 SQL files)

| File | Placeholder Count | Tables Referenced |
|------|:-----------------:|-------------------|
| `app/sql/extract_column.sql` | 14 | `pg_namespace`, `svv_tables`, `pg_class_info`, `SVV_EXTERNAL_TABLES`, `pg_views`, `pg_class`, `pg_constraint`, `pg_attribute`, `SVV_COLUMNS` |
| `app/sql/extract_table.sql` | 14 | `pg_namespace`, `svv_tables`, `pg_class_info`, `SVV_EXTERNAL_TABLES`, `pg_views`, `SVV_COLUMNS` |
| `app/sql/extract_schema.sql` | 2 | `svv_all_schemas`, `svv_tables` |

### Files WITHOUT placeholder (notable)

| File | Reason |
|------|--------|
| `app/sql/tables_check.sql` | Uses bare `pg_namespace`, `svv_tables`, etc. (no placeholder) |
| `app/sql/tables_check_miner.sql` | Same as `tables_check.sql` |
| `app/sql/filter_metadata.sql` | Uses bare `svv_all_schemas` |
| `app/sql/extract_database.sql` | Uses bare `pg_database`, `svv_all_schemas` |
| `app/sql/extract_database_with_schema_count.sql` | Uses bare `svv_all_schemas`, `pg_namespace` |

**Key observation:** Not all SQL files received the `{cloned_schema}` treatment in Redshift. The `tables_check`, `filter_metadata`, and `extract_database` files still use bare catalog references. This is likely intentional -- these queries may run before the cloned schema is resolved, or they query tables not included in the clone set.

### Placeholder Usage Pattern

The placeholder is placed as a **prefix** to the table name with no separator:

```sql
-- Pattern: {cloned_schema}<table_name>
FROM {cloned_schema}svv_tables T
INNER JOIN {cloned_schema}pg_namespace N ON (N.oid = C.relnamespace)
LEFT JOIN {cloned_schema}SVV_EXTERNAL_TABLES E ON (...)
```

When resolved:
- **With clone:** `FROM atlan.svv_tables T`
- **Without clone:** `FROM svv_tables T` (Redshift resolves these from `pg_catalog` implicitly)

---

## 3. Custom Control Config Wiring

### workflow.json Configuration

**File:** `app/templates/workflow.json`

The Custom Control Config is exposed through two linked properties:

#### `control-config-strategy` (radio selector)

```json
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
        "help": "Controls custom experimental feature flags for the crawler",
        "placeholder": "Control Config"
    }
}
```

#### `control-config` (free-form JSON text field)

```json
"control-config": {
    "type": "string",
    "ui": {
        "label": "Custom Config",
        "help": "Custom JSON config controlling experimental feature flags for the crawler",
        "placeholder": "{\"feature_x\":true}",
        "hidden": false,
        "default": "{}"
    }
}
```

### Conditional Visibility (anyOf)

The `control-config` field is only required when `control-config-strategy` is `"custom"`:

```json
{
    "properties": {
        "advanced-config": { "const": "custom" },
        "control-config-strategy": { "const": "custom" }
    },
    "required": ["control-config"]
}
```

Both fields live under the `"advanced-config"` parent toggle (the user must first select "Advanced" config to see them). The chain is:

```
Advanced Config = "custom"
  └─ Control Config Strategy = "custom"
       └─ Custom Config (JSON text field) → visible & required
```

### UI Placement

Both fields appear in the **Metadata** step:

```json
"steps": [
    {
        "id": "metadata",
        "title": "Metadata",
        "properties": [
            "include-filter",
            "exclude-filter",
            "temp-table-regex",
            "advanced-config",
            "cross-connection",
            "control-config-strategy",
            "control-config",
            ...
        ]
    }
]
```

### End-to-End Flow

```
┌─────────────────────────────────────────────────────────────┐
│  UI (workflow.json)                                         │
│  User selects: Advanced Config → Custom                     │
│  User selects: Control Config → Custom                      │
│  User enters: {"clonedPgCatalogSchema": "atlan"}           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Workflow Args (passed to activities)                       │
│  workflow_args = {                                          │
│      "control-config-strategy": "custom",                   │
│      "control-config": "{\"clonedPgCatalogSchema\":\"atlan\"}", │
│      "credentials": { "database": "mydb" },                │
│      ...                                                    │
│  }                                                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Activities (redshift.py)                                   │
│  fetch_schemas() / fetch_tables() / fetch_columns()         │
│     │                                                       │
│     └─ resolve_cloned_sql(workflow_args, self.fetch_*_sql)  │
│        │                                                    │
│        ├─ Reads "control-config-strategy" == "custom"       │
│        ├─ Parses "control-config" JSON                      │
│        ├─ Extracts "clonedPgCatalogSchema" → "atlan"        │
│        └─ Replaces {cloned_schema} → "atlan."               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Resolved SQL                                               │
│  FROM atlan.svv_tables T                                    │
│  INNER JOIN atlan.pg_namespace N ON (N.oid = C.relnamespace)│
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Redshift Documentation: Cloned Schema Setup

**File:** `atlan-docs/docs/apps/connectors/data-warehouses/amazon-redshift/how-tos/set-up-amazon-redshift.mdx`

### How the Docs Present It

The cloned schema is documented under the heading **"Cloned schema for restricted access"** within the **"Grant permissions for external schemas"** section, for both Provisioned and Serverless tabs.

### DBA Setup Steps (from docs)

1. Log in as `dbadmin`.
2. Create a new schema (e.g., `atlan`).
3. Clone these views as tables from `pg_catalog`:
   - `pg_views`
   - `SVV_TABLES`
   - `SVV_EXTERNAL_TABLES`
   - `SVV_COLUMNS`
4. Clone these views as tables from `information_schema`:
   - `key_column_usage` as `information_schema_key_column_usage`
   - `table_constraints` as `information_schema_table_constraints`
5. Grant access to the Atlan group/role on the cloned schema:
   ```sql
   GRANT USAGE ON SCHEMA <cloned_schema_name> TO GROUP atlan_users;
   GRANT SELECT ON ALL TABLES IN SCHEMA <cloned_schema_name> TO GROUP atlan_users;
   ```
6. Schedule a cron job to refresh the cloned tables periodically.

### Key Documentation Details

- The docs do **not** show the UI configuration for the Custom Control Config JSON field.
- The docs refer users to Atlan support for setup assistance.
- The information_schema tables are renamed with an `information_schema_` prefix in the clone (e.g., `information_schema_key_column_usage`), keeping them in the same clone schema.
- The emphasis is on periodic refresh via cron job since these are materialized copies, not live views.

---

## 5. Design Patterns Summary (for MySQL adaptation)

| Aspect | Redshift Pattern | MySQL Adaptation Notes |
|--------|-----------------|----------------------|
| **Config key** | `clonedPgCatalogSchema` | Use `clonedInformationSchema` |
| **Placeholder** | `{cloned_schema}` (prefix, no dot) | Use `{cloned_information_schema}` |
| **Replacement** | Empty string or `"<schema>."` | Same pattern: empty or `"<schema>."` |
| **Default** | `""` (resolves to bare system catalog names, Redshift implicit resolution) | `"information_schema."` (MySQL requires explicit schema prefix) |
| **Tables to clone** | `pg_views`, `SVV_TABLES`, `SVV_EXTERNAL_TABLES`, `SVV_COLUMNS`, `key_column_usage`, `table_constraints` | `SCHEMATA`, `TABLES`, `COLUMNS`, `VIEWS`, `PARTITIONS`, `ROUTINES`, `KEY_COLUMN_USAGE`, `TABLE_CONSTRAINTS` |
| **Affected SQL files** | 3 of 17 | 7 of 11 |
| **Activities wiring** | `resolve_cloned_sql()` called in `fetch_schemas`, `fetch_tables`, `fetch_columns` | Need equivalent calls plus `fetch_databases`, `fetch_procedures` |
| **Handler wiring** | N/A (Redshift handler does not use cloned SQL) | `metadata_sql` and `tables_check_sql` in MySQLHandler need treatment |
| **NOT IN exclusion** | `information_schema` in exclusion lists | Must add cloned schema name to `NOT IN` lists dynamically |
| **workflow.json** | `control-config-strategy` + `control-config` under `advanced-config` | Need to add `advanced-config`, `control-config-strategy`, `control-config` to MySQL workflow.json |

### Critical Difference: MySQL vs Redshift Default

In Redshift, `pg_catalog` tables like `svv_tables` can be referenced without a schema prefix because Redshift implicitly resolves them from `pg_catalog`. So `{cloned_schema}` defaults to `""`.

In MySQL, `information_schema` must be explicitly named. The current SQL uses `information_schema.TABLES`, `information_schema.COLUMNS`, etc. So the MySQL placeholder `{cloned_information_schema}` must default to `"information_schema."` (with trailing dot), not `""`.

This is the single most important design difference to get right.
