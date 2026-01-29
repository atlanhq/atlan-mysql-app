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
SELECT DISTINCT
    C.TABLE_CATALOG AS table_catalog,
    C.TABLE_SCHEMA AS table_schema,
    C.TABLE_NAME AS table_name,
    C.COLUMN_NAME AS column_name,
    C.ORDINAL_POSITION AS ordinal_position,
    C.COLUMN_DEFAULT AS column_def,
    C.IS_NULLABLE AS is_nullable,
    C.DATA_TYPE AS data_type,
    CASE
        WHEN C.EXTRA LIKE '%auto_increment%' THEN 'YES'
        ELSE 'NO'
    END AS is_auto_increment,
    C.NUMERIC_PRECISION AS numeric_precision,
    C.CHARACTER_OCTET_LENGTH AS character_octet_length,
    C.CHARACTER_OCTET_LENGTH AS buffer_length,
    CASE
        WHEN C.GENERATION_EXPRESSION IS NOT NULL THEN 'YES'
        ELSE 'NO'
    END AS is_generated,
    CASE
        WHEN C.GENERATION_EXPRESSION IS NOT NULL AND C.GENERATION_EXPRESSION != '' THEN 'YES'
        ELSE 'NO'
    END AS is_generatedcolumn,
    'NO' AS is_identity,
    NULL AS identity_cycle,
    CASE
        WHEN C.CHARACTER_MAXIMUM_LENGTH IS NOT NULL THEN C.CHARACTER_MAXIMUM_LENGTH
        WHEN C.NUMERIC_PRECISION IS NOT NULL THEN C.NUMERIC_PRECISION
        ELSE NULL
    END AS column_size,
    C.NUMERIC_SCALE AS num_prec_radix,
    C.NUMERIC_SCALE AS decimal_digits,
    T.TABLE_TYPE AS table_type,
    'NO' AS belongs_to_partition,
    'NO' AS partitioned_table,
    CASE
        WHEN (
            SELECT TC2.CONSTRAINT_TYPE
            FROM information_schema.KEY_COLUMN_USAGE KC2
            JOIN information_schema.TABLE_CONSTRAINTS TC2 ON (
                KC2.CONSTRAINT_SCHEMA = TC2.CONSTRAINT_SCHEMA
                AND KC2.CONSTRAINT_NAME = TC2.CONSTRAINT_NAME
                AND KC2.TABLE_SCHEMA = TC2.TABLE_SCHEMA
                AND KC2.TABLE_NAME = TC2.TABLE_NAME
            )
            WHERE KC2.TABLE_SCHEMA = C.TABLE_SCHEMA
                AND KC2.TABLE_NAME = C.TABLE_NAME
                AND KC2.COLUMN_NAME = C.COLUMN_NAME
                AND TC2.CONSTRAINT_TYPE = 'PRIMARY KEY'
            LIMIT 1
        ) IS NOT NULL THEN 'PRIMARY KEY'
        WHEN (
            SELECT TC2.CONSTRAINT_TYPE
            FROM information_schema.KEY_COLUMN_USAGE KC2
            JOIN information_schema.TABLE_CONSTRAINTS TC2 ON (
                KC2.CONSTRAINT_SCHEMA = TC2.CONSTRAINT_SCHEMA
                AND KC2.CONSTRAINT_NAME = TC2.CONSTRAINT_NAME
                AND KC2.TABLE_SCHEMA = TC2.TABLE_SCHEMA
                AND KC2.TABLE_NAME = TC2.TABLE_NAME
            )
            WHERE KC2.TABLE_SCHEMA = C.TABLE_SCHEMA
                AND KC2.TABLE_NAME = C.TABLE_NAME
                AND KC2.COLUMN_NAME = C.COLUMN_NAME
                AND TC2.CONSTRAINT_TYPE = 'FOREIGN KEY'
            LIMIT 1
        ) IS NOT NULL THEN 'FOREIGN KEY'
        ELSE NULL
    END AS constraint_type,
    (
        SELECT KC2.CONSTRAINT_NAME
        FROM information_schema.KEY_COLUMN_USAGE KC2
        JOIN information_schema.TABLE_CONSTRAINTS TC2 ON (
            KC2.CONSTRAINT_SCHEMA = TC2.CONSTRAINT_SCHEMA
            AND KC2.CONSTRAINT_NAME = TC2.CONSTRAINT_NAME
            AND KC2.TABLE_SCHEMA = TC2.TABLE_SCHEMA
            AND KC2.TABLE_NAME = TC2.TABLE_NAME
        )
        WHERE KC2.TABLE_SCHEMA = C.TABLE_SCHEMA
            AND KC2.TABLE_NAME = C.TABLE_NAME
            AND KC2.COLUMN_NAME = C.COLUMN_NAME
            AND TC2.CONSTRAINT_TYPE = 'PRIMARY KEY'
        LIMIT 1
    ) AS constraint_name,
    C.COLUMN_COMMENT AS remarks,
    NULL AS partition_order,
    NULL AS is_partition,
    C.NUMERIC_SCALE AS numeric_scale,
    CASE
        WHEN C.CHARACTER_MAXIMUM_LENGTH IS NOT NULL THEN C.CHARACTER_MAXIMUM_LENGTH
        ELSE 0
    END AS max_length,
    NULL AS is_self_referencing,
    -- MySQL-specific fields
    C.EXTRA AS extra_info,
    C.CHARACTER_SET_NAME AS character_set_name,
    C.COLLATION_NAME AS collation_name,
    C.COLUMN_TYPE AS column_type,
    C.COLUMN_KEY AS column_key,
    C.PRIVILEGES AS privileges,
    C.GENERATION_EXPRESSION AS generation_expression,
    CASE
        WHEN C.EXTRA LIKE '%auto_increment%' THEN 'YES'
        ELSE 'NO'
    END AS is_autoincrement

FROM
    information_schema.COLUMNS C
LEFT JOIN
    information_schema.TABLES T ON (C.TABLE_SCHEMA = T.TABLE_SCHEMA AND C.TABLE_NAME = T.TABLE_NAME)
WHERE
    C.TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
    AND CONCAT(COALESCE(DATABASE(), 'def'), CONCAT('.', C.TABLE_SCHEMA)) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(COALESCE(DATABASE(), 'def'), CONCAT('.', C.TABLE_SCHEMA)) REGEXP '{normalized_include_regex}'
    {temp_table_regex_sql}
ORDER BY
    C.TABLE_SCHEMA, C.TABLE_NAME, C.ORDINAL_POSITION;