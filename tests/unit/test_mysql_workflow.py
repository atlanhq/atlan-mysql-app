from datetime import timedelta
from typing import Any, Dict, List, TypeVar
from unittest.mock import MagicMock, Mock
from urllib.parse import quote_plus

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment

from app.activities.metadata_extraction.mysql import MySQLMetadataExtractionActivities
from app.clients import MySQLClient
from app.const import (
    COLUMN_EXTRACTION_SQL,
    DATABASE_EXTRACTION_SQL,
    FILTER_METADATA_SQL,
    PROCEDURE_EXTRACTION_SQL,
    SCHEMA_EXTRACTION_SQL,
    TABLE_EXTRACTION_SQL,
    TABLES_CHECK_SQL,
)
from app.handlers import MySQLWorkflowHandler
from app.transformers.atlas import MySQLAtlasTransformer, MySQLTable

# Type variables for activity results
T = TypeVar("T")
ActivityResult = Dict[str, List[Dict[str, str]]]
ActivityResults = Dict[str, ActivityResult]


def test_mysql_connection_string():
    """Test MySQL connection string generation."""
    client = MySQLClient()
    client.credentials = {
        "username": "test_user",
        "password": "test_pass",
        "host": "localhost",
        "port": 3306,
        "authType": "basic",
        "extra": {"database": "test_db"},
    }
    result = client.get_sqlalchemy_connection_string()
    expected = (
        f"mysql+pymysql://test_user:{quote_plus('test_pass')}@localhost:3306/test_db"
    )
    assert result == expected


def test_mysql_sql_query_attributes():
    """Test MySQL SQL query attributes."""
    activities = MySQLMetadataExtractionActivities()
    assert activities.fetch_database_sql == DATABASE_EXTRACTION_SQL
    assert activities.fetch_schema_sql == SCHEMA_EXTRACTION_SQL
    assert activities.fetch_table_sql == TABLE_EXTRACTION_SQL
    assert activities.fetch_column_sql == COLUMN_EXTRACTION_SQL
    assert activities.fetch_procedure_sql == PROCEDURE_EXTRACTION_SQL


def test_mysql_table_parsing():
    """Test MySQL table parsing."""
    table_data = {
        "table_name": "test_table",
        "table_type": "BASE TABLE",
        "table_schema": "test_schema",
        "table_catalog": "test_catalog",
        "connection_qualified_name": "default/mysql/test-connection",
        "table_comment": "Test table comment",
        "engine": "InnoDB",
        "row_format": "Dynamic",
        "table_collation": "utf8mb4_unicode_ci",
        "is_partition": "false",
        "partitioned_parent_table": "false",
        "table_kind": "r",  # Regular table
    }
    result = MySQLTable.get_attributes(table_data)
    assert result["attributes"]["name"] == "test_table"
    assert result["custom_attributes"]["engine"] == "InnoDB"
    assert result["custom_attributes"]["rowFormat"] == "Dynamic"
    assert result["custom_attributes"]["collation"] == "utf8mb4_unicode_ci"
    assert result["custom_attributes"]["tableType"] == "BASE TABLE"
    assert not result["attributes"]["is_partitioned"]


def test_mysql_client_connection_string():
    """Test MySQLClient connection string generation for different auth types"""
    # Test basic auth
    basic_credentials: Dict[str, Any] = {
        "username": "test_user",
        "password": "test@pass!123",
        "host": "localhost",
        "port": "3306",
        "extra": {"database": "test_db"},
        "authType": "basic",
    }

    client = MySQLClient()
    client.credentials = basic_credentials
    encoded_password = quote_plus(str(basic_credentials["password"]))
    database = basic_credentials.get("extra", {}).get("database", "")
    expected = f"mysql+pymysql://{basic_credentials['username']}:{encoded_password}@{basic_credentials['host']}:{basic_credentials['port']}/{database}"
    result = client.get_sqlalchemy_connection_string()
    assert result == expected

    # Test missing credentials
    with pytest.raises(KeyError):
        client.credentials = {}
        client.get_sqlalchemy_connection_string()

    # Test invalid auth type
    invalid_credentials = {
        "authType": "invalid",
        "username": "test_user",
        "password": "test_pass",
        "host": "localhost",
        "port": "3306",
        "extra": {"database": "test_db"},
    }
    client.credentials = invalid_credentials
    with pytest.raises(ValueError):
        client.get_sqlalchemy_connection_string()


def test_mysql_workflow_handler_sql_queries():
    """Test MySQLWorkflowHandler SQL query attributes"""
    handler = MySQLWorkflowHandler(sql_client=MagicMock())
    assert handler.metadata_sql == FILTER_METADATA_SQL
    assert handler.tables_check_sql == TABLES_CHECK_SQL


def test_mysql_activities_sql_queries():
    """Test MySQLActivities SQL query attributes"""
    activities = MySQLMetadataExtractionActivities()

    assert activities.fetch_database_sql == DATABASE_EXTRACTION_SQL
    assert activities.fetch_schema_sql == SCHEMA_EXTRACTION_SQL
    assert activities.fetch_table_sql == TABLE_EXTRACTION_SQL
    assert activities.fetch_column_sql == COLUMN_EXTRACTION_SQL
    assert activities.fetch_procedure_sql == PROCEDURE_EXTRACTION_SQL


def test_mysql_table():
    """Test parsing different types of MySQL tables"""
    # Test regular table
    table_data = {
        "table_type": "BASE TABLE",
        "table_name": "test_table",
        "table_schema": "test_db",
        "table_catalog": "test_db",
        "connection_qualified_name": "default/mysql/test-connection",
        "engine": "InnoDB",
        "row_format": "Dynamic",
        "table_collation": "utf8mb4_unicode_ci",
        "is_partition": "false",
        "partitioned_parent_table": "false",
        "table_kind": "r",  # Regular table
        "table_comment": "Test table",
    }
    result = MySQLTable.get_attributes(table_data)
    assert result["attributes"]["name"] == "test_table"
    assert result["custom_attributes"]["engine"] == "InnoDB"
    assert result["custom_attributes"]["rowFormat"] == "Dynamic"
    assert result["custom_attributes"]["collation"] == "utf8mb4_unicode_ci"
    assert result["custom_attributes"]["tableType"] == "BASE TABLE"
    assert not result["attributes"]["is_partitioned"]

    # Test view
    view_data = {
        "table_type": "VIEW",
        "table_name": "test_view",
        "table_schema": "test_db",
        "table_catalog": "test_db",
        "connection_qualified_name": "default/mysql/test-connection",
        "table_kind": "v",  # View
        "view_definition": "SELECT * FROM base_table",
        "is_partition": "false",
        "partitioned_parent_table": "false",
        "table_comment": "Test view",
    }
    result = MySQLTable.get_attributes(view_data)
    assert result["attributes"]["name"] == "test_view"
    assert result["custom_attributes"]["tableType"] == "VIEW"
    assert not result["attributes"]["is_partitioned"]


def test_custom_transformer_initialization():
    """Test MySQLAtlasTransformer initialization and entity class mappings"""
    transformer = MySQLAtlasTransformer(
        connector_name="test-connector", tenant_id="test-tenant"
    )

    assert transformer.entity_class_definitions["TABLE"] == MySQLTable


# Mock activities for testing
@activity.defn
async def fetch_databases() -> ActivityResult:
    return {"databases": [{"database_name": "test_db"}]}


@activity.defn
async def fetch_schemas() -> ActivityResult:
    return {"schemas": [{"schema_name": "test_db"}]}


@activity.defn
async def fetch_tables() -> ActivityResult:
    return {"tables": [{"table_name": "test_table"}]}


@activity.defn
async def fetch_columns() -> ActivityResult:
    return {"columns": [{"column_name": "test_column"}]}


@workflow.defn(sandboxed=False)
class MockExtractionWorkflow:
    @workflow.run
    async def run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        # Execute activities and collect results
        databases = await workflow.execute_activity(  # type: ignore
            fetch_databases, start_to_close_timeout=timedelta(seconds=30)
        )

        schemas = await workflow.execute_activity(  # type: ignore
            fetch_schemas, start_to_close_timeout=timedelta(seconds=30)
        )

        tables = await workflow.execute_activity(  # type: ignore
            fetch_tables, start_to_close_timeout=timedelta(seconds=30)
        )

        columns = await workflow.execute_activity(  # type: ignore
            fetch_columns, start_to_close_timeout=timedelta(seconds=30)
        )

        return {
            "status": "completed",
            "config": config,
            "data": {
                "databases": databases,
                "schemas": schemas,
                "tables": tables,
                "columns": columns,
            },
        }


@pytest.fixture
async def workflow_env():
    """Create a Temporal workflow environment for testing."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env
    finally:
        await env.shutdown()


@pytest.fixture
def mock_activities():
    """Create mock activities for testing."""
    activities = MagicMock(spec=MySQLMetadataExtractionActivities)

    # Set up async methods with proper return values and activity decorators
    @activity.defn
    async def mock_preflight_check(*args: Any, **kwargs: Any) -> Dict[str, str]:
        return {"status": "success"}

    @activity.defn
    async def mock_fetch_databases(*args: Any, **kwargs: Any) -> ActivityResult:
        return {"databases": [{"database_name": "test_db"}]}

    @activity.defn
    async def mock_fetch_schemas(*args: Any, **kwargs: Any) -> ActivityResult:
        return {"schemas": [{"schema_name": "test_schema"}]}

    @activity.defn
    async def mock_fetch_tables(*args: Any, **kwargs: Any) -> ActivityResult:
        return {"tables": [{"table_name": "test_table"}]}

    @activity.defn
    async def mock_fetch_columns(*args: Any, **kwargs: Any) -> ActivityResult:
        return {"columns": [{"column_name": "test_column"}]}

    @activity.defn
    async def mock_fetch_procedures(*args: Any, **kwargs: Any) -> ActivityResult:
        return {"procedures": [{"procedure_name": "test_procedure"}]}

    # Assign the async methods to the mock
    activities.preflight_check = mock_preflight_check
    activities.fetch_databases = mock_fetch_databases
    activities.fetch_schemas = mock_fetch_schemas
    activities.fetch_tables = mock_fetch_tables
    activities.fetch_columns = mock_fetch_columns
    activities.fetch_procedures = mock_fetch_procedures

    return activities


@pytest.fixture
def mock_handler():
    """Mock the MySQL workflow handler."""
    handler = Mock(spec=MySQLWorkflowHandler)
    handler.validate_connection.return_value = True
    return handler
