# Queries
TABLES_CHECK_SQL = """
   SELECT count(*) as count
   FROM information_schema.TABLES
   WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
       AND TABLE_SCHEMA NOT REGEXP '{normalized_exclude_regex}'
       AND TABLE_SCHEMA REGEXP '{normalized_include_regex}'
       {temp_table_regex_sql}
"""
TABLES_CHECK_TEMP_TABLE_REGEX_SQL = "AND TABLE_NAME NOT REGEXP '{exclude_table_regex}'"

TEST_AUTHENTICATION_SQL = "SELECT 1;"

FILTER_METADATA_SQL = """
SELECT
   catalog_name catalog_name,
   schema_name schema_name
FROM information_schema.SCHEMATA
WHERE schema_name NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
"""

### Extraction Queries


# MySQL database extraction query
DATABASE_EXTRACTION_SQL = """
SELECT
   SCHEMA_NAME database_name,
   DEFAULT_CHARACTER_SET_NAME,
   DEFAULT_COLLATION_NAME,
   CATALOG_NAME catalog_name
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY SCHEMA_NAME;
"""

# MySQL schema extraction query (in MySQL schema and database are synonymous)
SCHEMA_EXTRACTION_SQL = """
SELECT
   s.CATALOG_NAME catalog_name,
   s.SCHEMA_NAME schema_name,
   NULL schema_owner,
   COUNT(DISTINCT CASE WHEN t.TABLE_TYPE = 'BASE TABLE' THEN t.TABLE_NAME END) table_count,
   COUNT(DISTINCT CASE WHEN t.TABLE_TYPE = 'VIEW' THEN t.TABLE_NAME END) views_count
FROM information_schema.SCHEMATA s
LEFT JOIN information_schema.TABLES t ON s.SCHEMA_NAME = t.TABLE_SCHEMA
WHERE s.SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
   AND CONCAT(s.CATALOG_NAME, '.', s.SCHEMA_NAME) NOT REGEXP '{normalized_exclude_regex}'
    AND CONCAT(s.CATALOG_NAME, '.', s.SCHEMA_NAME) REGEXP '{normalized_include_regex}'
GROUP BY s.CATALOG_NAME, s.SCHEMA_NAME
ORDER BY s.SCHEMA_NAME
"""

# MySQL table extraction query
TABLE_EXTRACTION_SQL = """
   SELECT
   t.TABLE_CATALOG table_catalog,
   t.TABLE_SCHEMA table_schema,
   t.TABLE_NAME table_name,
   CASE
           WHEN t.table_type = 'BASE TABLE' THEN 'TABLE'
           ELSE t.table_type
   END AS table_type,
   EXISTS (
       SELECT 1 FROM INFORMATION_SCHEMA.PARTITIONS p
       WHERE p.TABLE_SCHEMA = t.TABLE_SCHEMA
       AND p.TABLE_NAME = t.TABLE_NAME
       AND p.PARTITION_NAME IS NOT NULL
   ) AS is_partition
   FROM
       INFORMATION_SCHEMA.TABLES t
   WHERE
       t.TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
        AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
        AND CONCAT(t.TABLE_CATALOG, '.', t.TABLE_SCHEMA) REGEXP '{normalized_include_regex}'
       {temp_table_regex_sql};
   """

TABLE_EXTRACTION_TEMP_TABLE_REGEX_SQL = (
    "AND t.TABLE_NAME NOT REGEXP '{exclude_table_regex}'"
)

# MySQL column extraction query
COLUMN_EXTRACTION_SQL = """
SELECT
   c.TABLE_CATALOG table_catalog,
   c.TABLE_SCHEMA table_schema,
   c.TABLE_NAME table_name,
   c.COLUMN_NAME column_name,
   c.ORDINAL_POSITION ordinal_position,
   c.COLUMN_DEFAULT column_def,
   c.IS_NULLABLE is_nullable,
   c.DATA_TYPE data_type,
   IF(c.EXTRA LIKE '%auto_increment%', 'YES', 'NO') is_auto_increment,
   c.NUMERIC_PRECISION numeric_precision,
   c.CHARACTER_OCTET_LENGTH character_octet_length,
   c.EXTRA is_generated,
   IF(c.EXTRA LIKE '%STORED GENERATED%', 'YES', 'NO') is_identity,
   NULL identity_cycle,
   c.CHARACTER_MAXIMUM_LENGTH column_size,
   10 num_prec_radix,
   c.NUMERIC_SCALE decimal_digits,
   t.TABLE_TYPE table_type,
   c.CHARACTER_SET_NAME character_set_name,
   c.COLLATION_NAME collation_name,
   c.COLUMN_COMMENT remarks,
   IF(tc.CONSTRAINT_TYPE = 'PRIMARY KEY', 'YES', 'NO') primary_key,
   kcu.REFERENCED_TABLE_SCHEMA fk_schema,
   kcu.REFERENCED_TABLE_NAME fk_table,
   kcu.REFERENCED_COLUMN_NAME fk_column,
   IF(tc.CONSTRAINT_TYPE = 'FOREIGN KEY', 'YES', 'NO') foreign_key,
   tc.CONSTRAINT_TYPE constraint_type,
   kcu.CONSTRAINT_NAME constraint_name,
   IF(p.PARTITION_NAME IS NOT NULL, 'YES', 'NO') belongs_to_partition,
   IF(p.PARTITION_NAME IS NOT NULL, 'YES', 'NO') partitioned_table,
   NULL partition_order,
   'r' table_kind
FROM
   INFORMATION_SCHEMA.COLUMNS c
JOIN
   INFORMATION_SCHEMA.TABLES t ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
LEFT JOIN
   INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu ON
   c.TABLE_SCHEMA = kcu.TABLE_SCHEMA AND
   c.TABLE_NAME = kcu.TABLE_NAME AND
   c.COLUMN_NAME = kcu.COLUMN_NAME
LEFT JOIN
   INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc ON
   kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME AND
   kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA AND
   kcu.TABLE_NAME = tc.TABLE_NAME
LEFT JOIN
   INFORMATION_SCHEMA.PARTITIONS p ON
   c.TABLE_SCHEMA = p.TABLE_SCHEMA AND
   c.TABLE_NAME = p.TABLE_NAME AND
   p.PARTITION_NAME IS NOT NULL
WHERE
   c.TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
   AND CONCAT(c.TABLE_CATALOG, '.', c.TABLE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
   AND CONCAT(c.TABLE_CATALOG, '.', c.TABLE_SCHEMA) REGEXP '{normalized_include_regex}'
   {temp_table_regex_sql}
ORDER BY
   c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION, tc.CONSTRAINT_TYPE
"""
COLUMN_EXTRACTION_TEMP_TABLE_REGEX_SQL = (
    "AND c.TABLE_NAME NOT REGEXP '{exclude_table_regex}'"
)

# MySQL procedure extraction query
PROCEDURE_EXTRACTION_SQL = """
SELECT
   r.ROUTINE_CATALOG procedure_catalog,
   r.ROUTINE_SCHEMA procedure_schema,
   r.ROUTINE_NAME procedure_name,
   r.DEFINER source_owner,
   r.ROUTINE_DEFINITION procedure_definition,
   r.ROUTINE_TYPE procedure_type,
   r.CREATED created,
   r.LAST_ALTERED last_altered,
   r.ROUTINE_COMMENT remarks,
   r.DEFINER proc_owner
FROM information_schema.ROUTINES r
WHERE r.ROUTINE_SCHEMA NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
   AND CONCAT(r.ROUTINE_CATALOG, '.', r.ROUTINE_SCHEMA) NOT REGEXP '{normalized_exclude_regex}'
   AND CONCAT(r.ROUTINE_CATALOG, '.', r.ROUTINE_SCHEMA) REGEXP '{normalized_include_regex}'
ORDER BY r.ROUTINE_SCHEMA, r.ROUTINE_NAME
"""
