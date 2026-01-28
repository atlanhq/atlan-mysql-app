/*
 * File: filter_metadata.sql
 * Purpose: Retrieves basic schema information for metadata filtering
 *
 * This query returns a list of schema names from the current database,
 * excluding system schemas. Used for initial metadata discovery and filtering.
 *
 * Returns:
 *   - Catalog name (database name)
 *   - Schema names
 *
 * Notes:
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 */
SELECT
    'def' AS catalog_name,
    S.SCHEMA_NAME AS schema_name
FROM information_schema.SCHEMATA S
WHERE S.SCHEMA_NAME NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')