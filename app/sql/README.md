# MySQL SQL Queries

This directory contains MySQL-specific SQL queries for metadata extraction. These queries have been converted from PostgreSQL to work with MySQL's information_schema tables.

## Query Files

### Core Queries

- **`client_version.sql`**: Retrieves MySQL server version using `VERSION()` function
- **`test_authentication.sql`**: Simple connectivity test with `SELECT 1`
- **`extract_database.sql`**: Extracts database metadata from `information_schema.SCHEMATA`
- **`extract_schema.sql`**: Extracts schema information with table/view counts
- **`extract_table.sql`**: Extracts comprehensive table and view metadata
- **`extract_column.sql`**: Extracts detailed column metadata with constraints
- **`extract_procedure.sql`**: Extracts stored procedures and functions from `information_schema.ROUTINES`

### Utility Queries

- **`tables_check.sql`**: Counts tables matching filter criteria for validation
- **`filter_metadata.sql`**: Lists schemas for metadata filtering
- **`extract_temp_table_regex_table.sql`**: SQL fragment for table name filtering
- **`extract_temp_table_regex_column.sql`**: SQL fragment for column filtering

## Key Conversions from PostgreSQL

### System Catalogs → Information Schema

| PostgreSQL | MySQL |
|------------|-------|
| `pg_database` | `information_schema.SCHEMATA` |
| `pg_namespace` | `information_schema.SCHEMATA` |
| `pg_class` | `information_schema.TABLES` |
| `pg_attribute` | `information_schema.COLUMNS` |
| `pg_proc` | `information_schema.ROUTINES` |

### Functions

| PostgreSQL | MySQL |
|------------|-------|
| `current_database()` | `DATABASE()` |
| `version()` | `VERSION()` |
| `concat()` | `CONCAT()` |

### Regex Operators

| PostgreSQL | MySQL |
|------------|-------|
| `column !~ 'pattern'` | `column NOT REGEXP 'pattern'` |
| `column ~ 'pattern'` | `column REGEXP 'pattern'` |

### Schema Exclusions

| PostgreSQL | MySQL |
|------------|-------|
| Exclude `pg_%`, `information_schema` | Exclude `mysql`, `performance_schema`, `information_schema`, `sys` |

## Query Parameters

All queries support template parameters for filtering:

- `{normalized_exclude_regex}`: Regex pattern for schemas to exclude
- `{normalized_include_regex}`: Regex pattern for schemas to include
- `{temp_table_regex_sql}`: Optional SQL fragment for temporary table filtering
- `{exclude_table_regex}`: Regex pattern for table names to exclude

## Notes

- MySQL doesn't have the same partitioning concepts as PostgreSQL, so partition-related fields are set to NULL or default values
- MySQL's `information_schema` provides most metadata needed, eliminating complex system catalog joins
- Character encoding is handled with `utf8mb4` charset for full UTF-8 support
- Storage engine information is available in MySQL and included in table metadata

## Example Usage

```sql
-- Get all tables in current database excluding system schemas
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
AND TABLE_SCHEMA = DATABASE();
```