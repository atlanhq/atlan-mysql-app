/*
 * File: extract_table.sql
 * Purpose: Extracts detailed table and view metadata from MySQL database
 *
 * Parameters:
 *   {normalized_exclude_regex} - Regex pattern for schemas to exclude
 *   {normalized_include_regex} - Regex pattern for schemas to include
 *   {temp_table_regex_sql} - Optional SQL for filtering temporary tables
 *
 * Returns:
 *   - Comprehensive table metadata including:
 *     - Table names, schemas, and types (table, view)
 *     - Row and column counts
 *     - View definitions
 *     - Table remarks/descriptions
 *     - Storage engine information
 *
 * Notes:
 *   - Only includes regular tables and views (TABLE_TYPE IN ('BASE TABLE', 'VIEW'))
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 *   - Uses information_schema for metadata extraction
 */
SELECT
    T.TABLE_CATALOG,
    T.TABLE_SCHEMA,
    T.TABLE_NAME,
    COALESCE(ST.TABLE_ROWS, 0) AS ROW_COUNT,
    (
        SELECT COUNT(*)
        FROM information_schema.COLUMNS C
        WHERE C.TABLE_SCHEMA = T.TABLE_SCHEMA
        AND C.TABLE_NAME = T.TABLE_NAME
    ) AS COLUMN_COUNT,
    T.TABLE_TYPE AS TABLE_KIND,
    T.TABLE_TYPE,
    FALSE AS IS_PARTITION,
    NULL AS PARTITION_STRATEGY,
    0 AS PARTITION_COUNT,
    NULL AS PARENT_TABLE_NAME,
    NULL AS PARTITIONED_PARENT_TABLE,
    NULL AS PARTITION_CONSTRAINT,
    0 AS NUMBER_COLUMNS_IN_PART_KEY,
    NULL AS COLUMNS_PARTICIPATING_IN_PART_KEY,
    V.VIEW_DEFINITION,
    NULL AS SELF_REFERENCING_COLUMN_NAME,
    NULL AS REFERENCE_GENERATION,
    NULL AS USER_DEFINED_TYPE_CATALOG,
    NULL AS USER_DEFINED_TYPE_SCHEMA,
    NULL AS USER_DEFINED_TYPE_NAME,
    CASE WHEN T.TABLE_TYPE = 'VIEW' THEN 'YES' ELSE 'NO' END AS IS_INSERTABLE_INTO,
    'NO' AS IS_TYPED,
    NULL AS COMMIT_ACTION,
    T.TABLE_COMMENT AS REMARKS,
    COALESCE(ST.DATA_LENGTH + ST.INDEX_LENGTH, 0) AS size_bytes,
    NULL AS location,
    NULL AS file_format_type,
    NULL AS stage_region,
    ST.ENGINE AS engine,
    NULL AS ref_generation
FROM information_schema.TABLES T
LEFT JOIN information_schema.TABLE_STATISTICS ST ON (T.TABLE_SCHEMA = ST.TABLE_SCHEMA AND T.TABLE_NAME = ST.TABLE_NAME)
LEFT JOIN information_schema.VIEWS V ON (T.TABLE_SCHEMA = V.TABLE_SCHEMA AND T.TABLE_NAME = V.TABLE_NAME)
WHERE T.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
AND CONCAT(DATABASE(), CONCAT('.', T.TABLE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
AND CONCAT(DATABASE(), CONCAT('.', T.TABLE_SCHEMA)) REGEXP '{normalized_include_regex}'
{temp_table_regex_sql}
AND T.TABLE_TYPE IN ('BASE TABLE', 'VIEW');