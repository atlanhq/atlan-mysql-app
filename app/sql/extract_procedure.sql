/*
 * File: extract_procedure.sql
 * Purpose: Extracts stored procedure metadata from MySQL database
 *
 * Parameters:
 *   {normalized_exclude_regex} - Regex pattern for schemas to exclude
 *   {normalized_include_regex} - Regex pattern for schemas to include
 *
 * Returns:
 *   - Procedure metadata including:
 *     - Procedure schema and name
 *     - Source owner (creator)
 *     - Procedure definition (source code)
 *     - Procedure type (PROCEDURE or FUNCTION)
 *
 * Notes:
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 *   - Results filtered by include/exclude regex patterns
 */
SELECT
    '{database_placeholder}' AS procedure_catalog,
    R.ROUTINE_SCHEMA AS procedure_schema,
    R.ROUTINE_NAME AS procedure_name,
    R.DEFINER AS source_owner,
    R.ROUTINE_DEFINITION AS procedure_definition,
    R.ROUTINE_TYPE AS procedure_type,
    R.ROUTINE_COMMENT AS remarks,
    -- MySQL-specific timestamps
    R.CREATED AS created,
    R.LAST_ALTERED AS last_altered
FROM information_schema.ROUTINES R
WHERE R.ROUTINE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
AND CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', R.ROUTINE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
AND CONCAT(COALESCE(DATABASE(), '{database_placeholder}'), CONCAT('.', R.ROUTINE_SCHEMA)) REGEXP '{normalized_include_regex}';