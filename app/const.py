# Queries
TABLES_CHECK_SQL = """
    SELECT count(*) count
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME NOT LIKE '{exclude_table}'
        AND CONCAT(TABLE_CATALOG, '.', TABLE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
        AND CONCAT(TABLE_CATALOG, '.', TABLE_SCHEMA) REGEXP '{normalized_include_regex}'
        AND TABLE_SCHEMA NOT IN ('performance_schema', 'information_schema', 'mysql','sys')
"""

TEST_AUTHENTICATION_SQL = "SELECT 1;"

FILTER_METADATA_SQL = """
SELECT schema_name schema_name, catalog_name catalog_name
FROM INFORMATION_SCHEMA.SCHEMATA
WHERE schema_name NOT IN ('information_schema', 'performance_schema','mysql','sys');
"""

### Extraction Queries

DATABASE_EXTRACTION_SQL = """
SELECT SCHEMA_NAME AS datname
FROM INFORMATION_SCHEMA.SCHEMATA
WHERE schema_name NOT IN ('information_schema', 'performance_schema','mysql','sys');
"""

SCHEMA_EXTRACTION_SQL = """
SELECT
    s.CATALOG_NAME catalog_name,
    s.SCHEMA_NAME schema_name,
    s.DEFAULT_CHARACTER_SET_NAME default_character_set_name,
    s.DEFAULT_COLLATION_NAME default_collation_name,
    s.SQL_PATH sql_path,
    s.DEFAULT_ENCRYPTION default_encryption,
    CAST(table_counts.table_count AS CHAR) AS table_count,
    CAST(table_counts.view_count AS CHAR) AS view_count
FROM
    information_schema.schemata s
LEFT JOIN (
    SELECT
        table_schema,
        SUM(CASE WHEN table_type = 'BASE TABLE' THEN 1 ELSE 0 END) as table_count,
        SUM(CASE WHEN table_type = 'VIEW' THEN 1 ELSE 0 END) as view_count
    FROM
        information_schema.tables
    GROUP BY
        table_schema
) as table_counts
ON s.schema_name = table_counts.table_schema
WHERE s.schema_name NOT IN ('information_schema', 'performance_schema', 'mysql','sys')
    AND CONCAT(s.CATALOG_NAME, '.', s.SCHEMA_NAME) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(s.CATALOG_NAME, '.', s.SCHEMA_NAME) REGEXP '{normalized_include_regex}';
"""

TABLE_EXTRACTION_SQL = """
    SELECT
    t.TABLE_CATALOG table_catalog,
    t.TABLE_SCHEMA table_schema,
    t.TABLE_NAME table_name,
    CASE
            WHEN t.table_type = 'BASE TABLE' THEN 'TABLE'
            ELSE t.table_type
    END AS table_type,
    CASE
        WHEN MAX(p.PARTITION_NAME) IS NOT NULL THEN true
        ELSE false
    END AS is_partition
    FROM
        INFORMATION_SCHEMA.TABLES t
    LEFT JOIN
        INFORMATION_SCHEMA.PARTITIONS p
    ON
        t.TABLE_SCHEMA = p.TABLE_SCHEMA
        AND t.TABLE_NAME = p.TABLE_NAME
    WHERE
        t.TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
        AND t.TABLE_NAME NOT REGEXP '{exclude_table}'
        AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
        AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) REGEXP '{normalized_include_regex}'
    GROUP BY
        t.TABLE_CATALOG,
        t.TABLE_SCHEMA,
        t.TABLE_NAME,
        t.TABLE_TYPE;
    """


COLUMN_EXTRACTION_SQL = """
SELECT
    TABLE_CATALOG table_catalog,
    TABLE_SCHEMA table_schema,
    TABLE_NAME table_name,
    COLUMN_NAME column_name,
    ORDINAL_POSITION ordinal_position,
    IS_NULLABLE is_nullable,
    DATA_TYPE data_type,
    CASE
        WHEN EXTRA LIKE '%auto_increment%' THEN 'YES'
        ELSE 'NO'
    END AS is_autoincrement
FROM
    INFORMATION_SCHEMA.COLUMNS t
WHERE
    TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
    AND t.TABLE_NAME NOT REGEXP '{exclude_table}'
    AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) REGEXP '{normalized_include_regex}'
ORDER BY
    TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;
"""


PROCEDURE_EXTRACTION_SQL = """
SELECT
    ROUTINE_CATALOG TABLE_CAT,
    ROUTINE_SCHEMA TABLE_SCHEM,
    ROUTINE_SCHEMA PROCEDURE_SCHEM,
    ROUTINE_NAME PROCEDURE_NAME,
    DEFINER PROC_OWNER,
    ROUTINE_DEFINITION ROUTINE_DEFINITION
FROM INFORMATION_SCHEMA.ROUTINES
WHERE ROUTINE_TYPE = 'PROCEDURE'
AND ROUTINE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
AND CONCAT(t.ROUTINE_CATALOG, '.', t.ROUTINE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
AND CONCAT(t.ROUTINE_CATALOG, '.', t.ROUTINE_SCHEMA) REGEXP '{normalized_include_regex}';
"""
