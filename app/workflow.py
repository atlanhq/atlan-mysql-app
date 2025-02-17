import logging
from urllib.parse import quote_plus

from application_sdk.workflows.sql.builders.builder import SQLWorkflowBuilder
from application_sdk.workflows.sql.controllers.metadata import (
    SQLWorkflowMetadataController,
)
from application_sdk.workflows.sql.controllers.preflight_check import (
    SQLWorkflowPreflightCheckController,
)
from application_sdk.workflows.sql.resources.sql_resource import (
    SQLResource,
    SQLResourceConfig,
)
from application_sdk.workflows.sql.workflows.workflow import SQLWorkflow

from app.const import (
    COLUMN_EXTRACTION_SQL,
    DATABASE_EXTRACTION_SQL,
    FILTER_METADATA_SQL,
    SCHEMA_EXTRACTION_SQL,
    TABLE_EXTRACTION_SQL,
    TABLES_CHECK_SQL,
)

logger = logging.getLogger(__name__)

APPLICATION_NAME = "mysql"


class MysqlResource(SQLResource):
    """MySQL specific implementation of SQLResource.
    
    Handles MySQL connection string generation with proper credential encoding.
    """

    def get_sqlalchemy_connection_string(self) -> str:
        """Generates a SQLAlchemy connection string for MySQL.

        Returns:
            str: A formatted MySQL connection string with encoded credentials.
        """
        encoded_password = quote_plus(self.config.credentials["password"])
        return f"mysql+pymysql://{self.config.credentials['user']}:{encoded_password}@{self.config.credentials['host']}:{self.config.credentials['port']}/{self.config.credentials['database']}"


class MysqlWorkflowMetadata(SQLWorkflowMetadataController):
    """Controller for handling MySQL metadata workflow operations.

    Attributes:
        METADATA_SQL (str): SQL query for filtering metadata.
    """
    METADATA_SQL = FILTER_METADATA_SQL


class MysqlWorkflowPreflight(SQLWorkflowPreflightCheckController):
    """Controller for MySQL preflight check operations.

    Attributes:
        METADATA_SQL (str): SQL query for filtering metadata.
        TABLES_CHECK_SQL (str): SQL query for validating tables.
    """
    METADATA_SQL = FILTER_METADATA_SQL
    TABLES_CHECK_SQL = TABLES_CHECK_SQL


class MysqlWorkflow(SQLWorkflow):
    """Main MySQL workflow implementation.

    Handles database, schema, table, and column extraction operations for MySQL.

    Attributes:
        fetch_database_sql (str): SQL query for database extraction.
        fetch_schema_sql (str): SQL query for schema extraction.
        fetch_table_sql (str): SQL query for table extraction.
        fetch_column_sql (str): SQL query for column extraction.
        sql_resource (SQLResource): Resource handler for MySQL operations.
    """
    fetch_database_sql = DATABASE_EXTRACTION_SQL
    fetch_schema_sql = SCHEMA_EXTRACTION_SQL
    fetch_table_sql = TABLE_EXTRACTION_SQL
    fetch_column_sql = COLUMN_EXTRACTION_SQL

    sql_resource: SQLResource | None = MysqlResource(SQLResourceConfig())


class MysqlWorkflowBuilder(SQLWorkflowBuilder):
    """Builder class for creating MySQL workflow instances.

    Args:
        application_name (str, optional): Name of the application. Defaults to APPLICATION_NAME.
    """
    def __init__(self, application_name: str = APPLICATION_NAME):
        """Initialize the MySQL workflow builder.

        Args:
            application_name (str, optional): Name of the application. Defaults to APPLICATION_NAME.
        """
        super().__init__()

    def build(self, workflow: SQLWorkflow | None = None) -> SQLWorkflow:
        """Build a MySQL workflow instance.

        Args:
            workflow (SQLWorkflow | None, optional): Base workflow to build from. Defaults to None.

        Returns:
            SQLWorkflow: Configured MySQL workflow instance.
        """
        return super().build(workflow=workflow or MysqlWorkflow())
