from application_sdk.handlers.sql import SQLHandler

from app.const import (
    FILTER_METADATA_SQL,
    TABLES_CHECK_SQL,
    TABLES_CHECK_TEMP_TABLE_REGEX_SQL,
)


class MySQLWorkflowHandler(SQLHandler):
    """
    Handler class for MySQL SQL workflows
    """

    # Variables for metadata queries
    metadata_sql = FILTER_METADATA_SQL
    tables_check_sql = TABLES_CHECK_SQL
    temp_table_regex_sql = TABLES_CHECK_TEMP_TABLE_REGEX_SQL
