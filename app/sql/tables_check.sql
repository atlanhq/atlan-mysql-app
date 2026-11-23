/*
 * File: tables_check.sql
 * Purpose: Counts accessible tables matching filter criteria
 *
 * Parameters:
 *   {normalized_exclude_regex} - Regex pattern for schemas to exclude
 *   {normalized_include_regex} - Regex pattern for schemas to include
 *   {temp_table_regex_sql} - Optional SQL for filtering temporary tables
 *
 * Returns: Count of tables/views matching the specified criteria
 *
 * Notes:
 *   - Used for validation and performance estimation
 *   - Includes only tables of types: 'BASE TABLE', 'VIEW'
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 */
SELECT COUNT(*) as count
FROM information_schema.TABLES T
WHERE CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', T.TABLE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', T.TABLE_SCHEMA)) REGEXP '{normalized_include_regex}'
    AND T.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
    AND T.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
    {temp_table_regex_sql}