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
    def get_sqlalchemy_connection_string(self) -> str:
        encoded_password = quote_plus(self.config.credentials["password"])
        return f"mysql+pymysql://{self.config.credentials['user']}:{encoded_password}@{self.config.credentials['host']}:{self.config.credentials['port']}/{self.config.credentials['database']}"


class MysqlWorkflowMetadata(SQLWorkflowMetadataController):
    METADATA_SQL = FILTER_METADATA_SQL


class MysqlWorkflowPreflight(SQLWorkflowPreflightCheckController):
    METADATA_SQL = FILTER_METADATA_SQL
    TABLES_CHECK_SQL = TABLES_CHECK_SQL


class MysqlWorkflow(SQLWorkflow):
    fetch_database_sql = DATABASE_EXTRACTION_SQL
    fetch_schema_sql = SCHEMA_EXTRACTION_SQL
    fetch_table_sql = TABLE_EXTRACTION_SQL
    fetch_column_sql = COLUMN_EXTRACTION_SQL

    sql_resource: SQLResource | None = MysqlResource(SQLResourceConfig())


class MysqlWorkflowBuilder(SQLWorkflowBuilder):
    def __init__(self, application_name: str = APPLICATION_NAME):
        super().__init__()

    def build(self, workflow: SQLWorkflow | None = None) -> SQLWorkflow:
        return super().build(workflow=workflow or MysqlWorkflow())
