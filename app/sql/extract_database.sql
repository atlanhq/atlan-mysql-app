/*
 * File: extract_database.sql
 * Purpose: Extracts basic database metadata from the current MySQL database
 *
 * This query retrieves fundamental database information including database name
 * and all associated metadata from the information_schema.schemata table.
 *
 * Returns:
 *   - Database metadata including name and system properties
 *
 * Notes:
 *   - Scoped to the current database (DATABASE())
 */
SELECT
    'def' as database_name,
    'def' as datname,
    DEFAULT_CHARACTER_SET_NAME as charset,
    DEFAULT_COLLATION_NAME as collation,
    (
        SELECT COUNT(*)
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME NOT IN ('performance_schema', 'information_schema', 'mysql', 'sys')
    ) as schema_count
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME = COALESCE(DATABASE(), 'def');