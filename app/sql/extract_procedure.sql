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
    R.ROUTINE_CATALOG AS PROCEDURE_CATALOG,
    R.ROUTINE_SCHEMA  AS PROCEDURE_SCHEMA,
    R.ROUTINE_NAME    AS PROCEDURE_NAME,
    R.DEFINER         AS SOURCE_OWNER,
    R.ROUTINE_DEFINITION AS procedure_definition,
    R.ROUTINE_TYPE    AS procedure_type
FROM information_schema.ROUTINES R
WHERE R.ROUTINE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
AND CONCAT(DATABASE(), CONCAT('.', R.ROUTINE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
AND CONCAT(DATABASE(), CONCAT('.', R.ROUTINE_SCHEMA)) REGEXP '{normalized_include_regex}';