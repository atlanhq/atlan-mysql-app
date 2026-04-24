# Capability Research: Custom INFORMATION_SCHEMA Mirror for MySQL

## Problem Statement

MySQL's architecture ties `INFORMATION_SCHEMA` visibility to actual data privileges — a user can only see metadata for objects they have `SELECT` privilege on. This is a MySQL engine constraint, not an Atlan choice. Enterprise customers (e.g., Bandwidth) with strict infosec policies are blocked from granting `SELECT ON *.*` even when extraction happens on their infrastructure via SDR.

## Proposed Solution

Allow customers to create a mirror schema containing views/tables that replicate the `INFORMATION_SCHEMA` content Atlan needs, then configure the MySQL connector to query that mirror instead of `information_schema.*` directly.

## MySQL INFORMATION_SCHEMA Architecture

- MySQL's `INFORMATION_SCHEMA` is a virtual database — it does not contain physical tables
- Each "table" is actually a view over internal MySQL metadata
- Access is filtered based on the user's privileges on underlying objects
- Reference: [MySQL 8.4 INFORMATION_SCHEMA Introduction](https://dev.mysql.com/doc/refman/8.4/en/information-schema-introduction.html)

### Mirror Schema Approach

The customer creates a real schema with materialized copies:
```sql
CREATE SCHEMA atlan_metadata;

-- Example: mirror the TABLES view
CREATE TABLE atlan_metadata.TABLES AS
SELECT * FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys');
```

The customer grants `SELECT` only on this mirror schema to the Atlan service account — no direct table access needed.

### MariaDB 10.11 Considerations

MariaDB 10.11 is largely compatible with MySQL's INFORMATION_SCHEMA but has some differences:
- Additional columns in some tables (e.g., `MAX_INDEX_LENGTH`, `TEMPORARY` in TABLES)
- Different `ENGINE` column values for views
- The `ROUTINES` table may have different column names for some fields

The SQL queries should work on both since we SELECT specific columns, but the DBA setup script should note MariaDB-specific caveats.

## Existing Precedent: Redshift

See `similar-patterns.md` for full deep-dive. Key takeaway: Redshift has had this feature in production, exposed via Custom Control Config with a `clonedPgCatalogSchema` key. The MySQL implementation follows the same architectural pattern.

## Key Design Decision: Default Value

**Critical difference from Redshift**: Redshift's `resolve_cloned_sql()` defaults `{cloned_schema}` to `""` (empty string) because `pg_catalog` tables are accessible without a schema prefix. MySQL requires the schema prefix — `information_schema.TABLES` works but bare `TABLES` does not. Therefore, the MySQL utility must default to `"information_schema."` (with trailing dot).
