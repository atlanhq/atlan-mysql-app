/*
 * File: extract_schema.sql
 * Purpose: Extracts schema metadata from MySQL database
 *
 * Parameters:
 *   {normalized_exclude_regex} - Regex pattern for schemas to exclude
 *   {normalized_include_regex} - Regex pattern for schemas to include
 *
 * Returns:
 *   - Schema metadata including name, owner, and table/view counts
 *   - Includes table and view counts per schema
 *
 * Notes:
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 *   - Results are filtered by include/exclude regex patterns
 *   - Ordered by schema name
 */
SELECT
    '{database_placeholder}' AS catalog_name,
    S.SCHEMA_NAME AS schema_name,
    'mysql' AS schema_owner,
    COALESCE(table_counts.table_count, 0) AS table_count,
    COALESCE(table_counts.views_count, 0) AS views_count
FROM information_schema.SCHEMATA S
LEFT JOIN
	(
	SELECT
		TABLE_SCHEMA,
	 	SUM(CASE WHEN TABLE_TYPE = 'BASE TABLE' THEN 1 ELSE 0 END) as table_count,
		SUM(CASE WHEN TABLE_TYPE = 'VIEW' THEN 1 ELSE 0 END) as views_count
	FROM information_schema.TABLES
	GROUP BY TABLE_SCHEMA
) as table_counts
ON (table_counts.TABLE_SCHEMA = S.SCHEMA_NAME)
WHERE
    S.SCHEMA_NAME NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
    AND CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', S.SCHEMA_NAME)) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', S.SCHEMA_NAME)) REGEXP '{normalized_include_regex}'
ORDER BY S.SCHEMA_NAME;