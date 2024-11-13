from urllib.parse import quote_plus
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from application_sdk.workflows.sql.builders.builder import SQLWorkflowBuilder
from application_sdk.workflows.sql.controllers.metadata import (
    SQLWorkflowMetadataController,
)
from application_sdk.workflows.sql.controllers.preflight_check import (
    SQLWorkflowPreflightCheckController,
)
from application_sdk.workflows.sql.workflows.workflow import SQLWorkflow
from application_sdk.workflows.transformers.phoenix import PhoenixTransformer
from application_sdk.workflows.sql.resources.sql_resource import SQLResourceConfig, SQLResource
from temporalio import activity
from app.const import (
    COLUMN_EXTRACTION_SQL,
    DATABASE_EXTRACTION_SQL,
    FILTER_METADATA_SQL,
    SCHEMA_EXTRACTION_SQL,
    TABLE_EXTRACTION_SQL,
    TABLES_CHECK_SQL,
)
from sqlalchemy import text

logger = logging.getLogger(__name__)

APPLICATION_NAME = "mysql-connector"


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

class MysqlWorkflowBuilder(SQLWorkflowBuilder):
    def __init__(self, application_name: str = APPLICATION_NAME):
        self.set_transformer(
            PhoenixTransformer(
                connector_name=application_name, connector_type="mysql"
            )
        )

        super().__init__()

    def build(self, workflow: SQLWorkflow | None = None) -> SQLWorkflow:
        return super().build(workflow=workflow or MysqlWorkflow())

class MysqlResource(SQLResource):
    
    async def run_query(self, query: str, batch_size: int = 100000):
        """
        Run a query in a batch mode with client-side cursor.

        This method also supports server-side cursor via sqlalchemy execution options(yield_per=batch_size)
        If yield_per is not supported by the database, the method will fall back to client-side cursor.

        :param query: The query to run.
        :param batch_size: The batch size.
        :return: The query results.
        :raises Exception: If the query fails.
        """
        loop = asyncio.get_running_loop()

        def execute_query():
            with self.engine.connect() as connection:
                if self.config.use_server_side_cursor:
                    connection = connection.execution_options(yield_per=batch_size)

                result = connection.execute(text(query))
                column_names: List[str] = []

                while True:
                    rows = result.fetchmany(batch_size)
                    if not rows:
                        break

                    if not column_names:
                        column_names = rows[0]._fields

                    results = [dict(zip(column_names, row)) for row in rows]
                    return results

        activity.logger.info(f"Running query: {query}")

        with ThreadPoolExecutor() as pool:
            try:
                results = await loop.run_in_executor(pool, execute_query)
                yield results
            except Exception as e:
                logger.error(f"Error running query in batch: {e}")
                raise e

        activity.logger.info("Query execution completed")
    

class MysqlSQLResourceConfig(SQLResourceConfig):
    def __init__(self):
        super().__init__()
    
    def get_sqlalchemy_connection_string(self) -> str:
        encoded_password = quote_plus(self.credentials["password"])
        return f"mysql+pymysql://{self.credentials['user']}:{encoded_password}@{self.credentials['host']}:{self.credentials['port']}/{self.credentials['database']}"
