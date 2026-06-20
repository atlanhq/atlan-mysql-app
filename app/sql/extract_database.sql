/*
 * File: extract_database.sql
 * Purpose: Extracts basic database metadata from MySQL
 *
 * This query retrieves catalog-level database information including the catalog name
 * and count of non-system schemas. Matches legacy JDBC extractor behavior.
 *
 * Returns:
 *   - Catalog metadata with name 'def' (MySQL's default catalog)
 *   - Count of non-system schemas
 *
 * Notes:
 *   - Returns exactly 1 row representing the catalog level
 *   - Uses 'def' as the catalog name (MySQL convention)
 *   - Counts all non-system schemas in the MySQL instance
 */
SELECT
    '{database_placeholder}' as database_name,
    '{database_placeholder}' as datname,
    (
        SELECT COUNT(*)
        FROM {information_schema}.SCHEMATA
        WHERE SCHEMA_NAME NOT IN ({excluded_schemas})
    ) as schema_count;