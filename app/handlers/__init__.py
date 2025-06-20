from application_sdk.application.metadata_extraction.sql import BaseSQLHandler


class MySQLHandler(BaseSQLHandler):
    """
    MySQL-specific handler for workflow requests.

    This class extends the base SQL handler and provides MySQL-specific
    SQL queries for preflight checks and metadata operations.
    """

    def __init__(self, sql_client=None):
        # Initialize the base class with MySQL client
        super().__init__(sql_client=sql_client)
