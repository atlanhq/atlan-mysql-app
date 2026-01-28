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
    T.TABLE_CATALOG AS table_catalog,
    T.TABLE_SCHEMA AS table_schema,
    T.TABLE_NAME AS table_name,
    COALESCE(T.TABLE_ROWS, 0) AS row_count,
    (
        SELECT COUNT(*)
        FROM information_schema.COLUMNS C
        WHERE C.TABLE_SCHEMA = T.TABLE_SCHEMA
        AND C.TABLE_NAME = T.TABLE_NAME
    ) AS column_count,
    T.TABLE_TYPE AS table_kind,
    T.TABLE_TYPE AS table_type,
    IF(p.PARTITION_METHOD IS NULL, FALSE, TRUE) AS is_partition,
    p.PARTITION_METHOD AS partition_strategy,
    IF(p.PARTITION_METHOD IS NULL, 0, p.partition_count) AS partition_count,
    T.TABLE_NAME AS parent_table_name,
    NULL AS partitioned_parent_table,
    NULL AS partition_constraint,
    0 AS number_columns_in_part_key,
    NULL AS columns_participating_in_part_key,
    V.VIEW_DEFINITION AS view_definition,
    NULL AS self_referencing_column_name,
    NULL AS reference_generation,
    NULL AS user_defined_type_catalog,
    NULL AS user_defined_type_schema,
    NULL AS user_defined_type_name,
    CASE WHEN T.TABLE_TYPE = 'VIEW' THEN 'YES' ELSE 'NO' END AS is_insertable_into,
    'NO' AS is_typed,
    NULL AS commit_action,
    T.TABLE_COMMENT AS remarks,
    COALESCE(T.DATA_LENGTH + T.INDEX_LENGTH, 0) AS size_bytes,
    NULL AS location,
    NULL AS file_format_type,
    NULL AS stage_region,
    T.ENGINE AS engine,
    NULL AS ref_generation,
    -- MySQL-specific fields
    T.VERSION AS version,
    T.ROW_FORMAT AS row_format,
    T.DATA_LENGTH AS data_length,
    T.AUTO_INCREMENT AS auto_increment,
    T.TABLE_COLLATION AS table_collation,
    T.CREATE_OPTIONS AS create_options,
    T.CREATE_TIME AS create_time,
    -- Partition metadata
    p.PARTITIONS AS partitions
FROM information_schema.TABLES T
LEFT JOIN (
    SELECT
        TABLE_NAME,
        TABLE_SCHEMA,
        PARTITION_METHOD,
        COUNT(*) AS partition_count,
        GROUP_CONCAT(PARTITION_NAME ORDER BY PARTITION_NAME) AS PARTITIONS
    FROM information_schema.PARTITIONS
    GROUP BY TABLE_NAME, TABLE_SCHEMA, PARTITION_METHOD
) AS p ON p.TABLE_NAME = T.TABLE_NAME AND p.TABLE_SCHEMA = T.TABLE_SCHEMA
LEFT JOIN information_schema.VIEWS V ON (T.TABLE_SCHEMA = V.TABLE_SCHEMA AND T.TABLE_NAME = V.TABLE_NAME)
WHERE T.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
AND CONCAT(DATABASE(), CONCAT('.', T.TABLE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
AND CONCAT(DATABASE(), CONCAT('.', T.TABLE_SCHEMA)) REGEXP '{normalized_include_regex}'
{temp_table_regex_sql}
AND T.TABLE_TYPE IN ('BASE TABLE', 'VIEW');