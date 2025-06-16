/*
 * File: extract_column.sql
 * Purpose: Extracts detailed column metadata from MySQL database
 *
 * Parameters:
 *   {normalized_exclude_regex} - Regex pattern for schemas to exclude
 *   {normalized_include_regex} - Regex pattern for schemas to include
 *   {temp_table_regex_sql} - Optional SQL for filtering temporary tables
 *
 * Returns:
 *   - Comprehensive column metadata including:
 *     - Column names, data types, and positions
 *     - Nullability and default values
 *     - Auto-increment and identity properties
 *     - Constraint information (primary key, foreign key, etc.)
 *     - Column descriptions/remarks
 *
 * Notes:
 *   - Uses information_schema.COLUMNS for column metadata
 *   - Excludes system schemas (mysql, performance_schema, information_schema, sys)
 *   - Includes constraint information from information_schema.KEY_COLUMN_USAGE
 *   - Results ordered by schema, table, and column position
 */
SELECT
    C.TABLE_CATALOG,
    C.TABLE_SCHEMA,
    C.TABLE_NAME,
    C.COLUMN_NAME,
    C.ORDINAL_POSITION,
    C.COLUMN_DEFAULT AS COLUMN_DEF,
    C.IS_NULLABLE,
    C.DATA_TYPE,
    CASE
        WHEN C.EXTRA LIKE '%auto_increment%' THEN 'YES'
        ELSE 'NO'
    END AS IS_AUTO_INCREMENT,
    C.NUMERIC_PRECISION,
    C.CHARACTER_OCTET_LENGTH,
    CASE
        WHEN C.GENERATION_EXPRESSION IS NOT NULL THEN 'YES'
        ELSE 'NO'
    END AS IS_GENERATED,
    'NO' AS IS_IDENTITY,
    NULL AS IDENTITY_CYCLE,
    CASE
        WHEN C.CHARACTER_MAXIMUM_LENGTH IS NOT NULL THEN C.CHARACTER_MAXIMUM_LENGTH
        WHEN C.NUMERIC_PRECISION IS NOT NULL THEN C.NUMERIC_PRECISION
        ELSE NULL
    END AS COLUMN_SIZE,
    C.NUMERIC_SCALE AS NUM_PREC_RADIX,
    C.NUMERIC_SCALE AS DECIMAL_DIGITS,
    T.TABLE_TYPE,
    'NO' AS BELONGS_TO_PARTITION,
    'NO' AS PARTITIONED_TABLE,
    CASE
        WHEN KC.CONSTRAINT_NAME IS NOT NULL THEN
            CASE
                WHEN TC.CONSTRAINT_TYPE = 'PRIMARY KEY' THEN 'PRIMARY KEY'
                WHEN TC.CONSTRAINT_TYPE = 'FOREIGN KEY' THEN 'FOREIGN KEY'
                WHEN TC.CONSTRAINT_TYPE = 'UNIQUE' THEN 'UNIQUE'
                WHEN TC.CONSTRAINT_TYPE = 'CHECK' THEN 'CHECK'
                ELSE TC.CONSTRAINT_TYPE
            END
        ELSE NULL
    END AS CONSTRAINT_TYPE,
    KC.CONSTRAINT_NAME,
    C.COLUMN_COMMENT AS REMARKS,
    NULL AS PARTITION_ORDER,
    NULL AS IS_PARTITION,
    C.NUMERIC_SCALE,
    CASE
        WHEN C.CHARACTER_MAXIMUM_LENGTH IS NOT NULL THEN C.CHARACTER_MAXIMUM_LENGTH
        ELSE 0
    END AS MAX_LENGTH,
    NULL AS IS_SELF_REFERENCING

FROM
    information_schema.COLUMNS C
LEFT JOIN
    information_schema.TABLES T ON (C.TABLE_SCHEMA = T.TABLE_SCHEMA AND C.TABLE_NAME = T.TABLE_NAME)
LEFT JOIN
    information_schema.KEY_COLUMN_USAGE KC ON (
        C.TABLE_SCHEMA = KC.TABLE_SCHEMA 
        AND C.TABLE_NAME = KC.TABLE_NAME 
        AND C.COLUMN_NAME = KC.COLUMN_NAME
    )
LEFT JOIN
    information_schema.TABLE_CONSTRAINTS TC ON (
        KC.CONSTRAINT_SCHEMA = TC.CONSTRAINT_SCHEMA 
        AND KC.CONSTRAINT_NAME = TC.CONSTRAINT_NAME
    )
WHERE
    C.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
    AND CONCAT(DATABASE(), CONCAT('.', C.TABLE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(DATABASE(), CONCAT('.', C.TABLE_SCHEMA)) REGEXP '{normalized_include_regex}'
    {temp_table_regex_sql}
    AND T.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
ORDER BY
    C.TABLE_SCHEMA, C.TABLE_NAME, C.ORDINAL_POSITION;