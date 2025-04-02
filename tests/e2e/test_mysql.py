import json
from datetime import timedelta
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock, patch

import pytest
from application_sdk.activities.common.models import ActivityStatistics

from app.activities.metadata_extraction.mysql import MySQLMetadataExtractionActivities
from app.clients import MySQLClient
from app.workflows.metadata_extraction.mysql import MySQLMetadataExtractionWorkflow


class AsyncIteratorMock:
    """Helper class to mock async iterators"""

    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self.items = items.copy()

    def __aiter__(self) -> "AsyncIteratorMock":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return self.items.pop(0)
        except IndexError:
            raise StopAsyncIteration


@pytest.fixture
def mock_activity_context() -> Generator[MagicMock, None, None]:
    """Mock activity context for testing"""
    with patch("temporalio.activity._Context.current") as mock_current:
        mock_context = MagicMock()
        mock_info = MagicMock()
        mock_info.workflow_id = "test-workflow"
        mock_info.activity_id = "test-activity-id"
        mock_info.heartbeat_timeout = timedelta(seconds=30)
        mock_info.start_to_close_timeout = timedelta(seconds=30)
        mock_context.info = mock_info
        mock_current.return_value = mock_context

        # Also patch the logger to avoid activity_id errors
        with patch("app.transformers.atlas.logger") as mock_logger:
            mock_logger.info = MagicMock()
            yield mock_context


@pytest.fixture
def mock_workflow_context() -> Generator[MagicMock, None, None]:
    """Mock workflow context for testing"""
    with patch("temporalio.workflow._Runtime.current") as mock_current:
        mock_runtime = MagicMock()
        mock_info = MagicMock()
        mock_info.run_id = "test-run-id"
        mock_info.workflow_id = "test-workflow"
        mock_info.workflow_type = "test-workflow-type"
        mock_info.task_queue = "test-task-queue"
        mock_runtime.workflow_info.return_value = mock_info
        mock_current.return_value = mock_runtime
        yield mock_runtime


@pytest.fixture
def mock_state_store() -> Generator[MagicMock, None, None]:
    """Mock state store for testing"""
    with patch("application_sdk.inputs.statestore.DaprClient") as mock_dapr:
        mock_client = MagicMock()
        mock_dapr.return_value.__enter__.return_value = mock_client

        # Mock get_state to return test configuration
        def mock_get_state(store_name: str, key: str) -> MagicMock:
            if key == "config_test-workflow":
                config = {
                    "workflow_id": "test-workflow",
                    "connection_qualified_name": "default/mysql/test-connection",
                    "output_path": "/tmp/test_output",
                    "output_prefix": "/tmp/test_output",
                    "tenant_id": "test-tenant",
                    "connection": {
                        "host": "localhost",
                        "port": 3306,
                        "username": "test_user",
                        "password": "test_pass",
                        "database": "test_db",
                    },
                }
                return MagicMock(data=json.dumps(config))
            return MagicMock(data=None)

        mock_client.get_state.side_effect = mock_get_state
        yield mock_client


@pytest.fixture
def mock_mysql_client() -> MagicMock:
    """Mock MySQL client for testing"""
    client = MagicMock(spec=MySQLClient)
    client.get_sqlalchemy_connection_string.return_value = (
        "mysql+pymysql://test_user:test_pass@localhost:3306/test_db"
    )
    return client


@pytest.fixture
def mysql_activities(mock_mysql_client: MagicMock) -> MySQLMetadataExtractionActivities:
    """Create MySQL activities instance with mocked client"""
    activities = MySQLMetadataExtractionActivities()
    setattr(
        activities, "mysql_client", mock_mysql_client
    )  # Use setattr to avoid type errors
    return activities


@pytest.fixture
def mysql_workflow() -> MySQLMetadataExtractionWorkflow:
    """Create MySQL workflow instance"""
    return MySQLMetadataExtractionWorkflow()


class TestMySQLClient:
    """Test MySQL client functionality"""

    def test_get_connection_string(self, mock_mysql_client: MagicMock) -> None:
        """Test getting SQLAlchemy connection string"""
        conn_str = mock_mysql_client.get_sqlalchemy_connection_string()
        assert "mysql+pymysql://" in conn_str
        assert "test_user" in conn_str
        assert "test_db" in conn_str


class TestMySQLMetadataExtractionActivities:
    """Test MySQL metadata extraction activities"""

    @pytest.mark.asyncio
    async def test_fetch_databases(
        self,
        mysql_activities: MySQLMetadataExtractionActivities,
        mock_activity_context: MagicMock,
    ) -> None:
        """Test database metadata extraction"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock database query results
        mysql_client = getattr(mysql_activities, "mysql_client")
        mysql_client.run_query.return_value = AsyncIteratorMock(
            [{"database_name": "db1"}, {"database_name": "db2"}]
        )

        # Execute database extraction
        result = await mysql_activities.fetch_databases(workflow_config)

        # Verify result structure
        assert result is not None
        assert isinstance(result, ActivityStatistics)
        assert result.typename == "database"
        assert result.total_record_count == 0
        assert result.chunk_count == 0

    @pytest.mark.asyncio
    async def test_fetch_schemas(
        self,
        mysql_activities: MySQLMetadataExtractionActivities,
        mock_activity_context: MagicMock,
    ) -> None:
        """Test schema metadata extraction"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock schema query results
        mysql_client = getattr(mysql_activities, "mysql_client")
        mysql_client.run_query.return_value = AsyncIteratorMock(
            [{"schema_name": "schema1"}, {"schema_name": "schema2"}]
        )

        # Execute schema extraction
        result = await mysql_activities.fetch_schemas(workflow_config)

        # Verify result structure
        assert result is not None
        assert isinstance(result, ActivityStatistics)
        assert result.typename == "schema"
        assert result.total_record_count == 0
        assert result.chunk_count == 0

    @pytest.mark.asyncio
    async def test_fetch_tables(
        self,
        mysql_activities: MySQLMetadataExtractionActivities,
        mock_activity_context: MagicMock,
    ) -> None:
        """Test table metadata extraction"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock table query results
        mysql_client = getattr(mysql_activities, "mysql_client")
        mysql_client.run_query.return_value = AsyncIteratorMock(
            [
                {
                    "table_name": "table1",
                    "table_type": "BASE TABLE",
                    "table_schema": "schema1",
                    "table_catalog": "def",
                    "connection_qualified_name": "default/mysql/test-connection",
                    "engine": "InnoDB",
                    "row_format": "Dynamic",
                    "table_collation": "utf8mb4_unicode_ci",
                    "is_partition": "false",
                    "partitioned_parent_table": "false",
                    "table_kind": "r",
                }
            ]
        )

        # Execute table extraction
        result = await mysql_activities.fetch_tables(workflow_config)

        # Verify result structure
        assert result is not None
        assert isinstance(result, ActivityStatistics)
        assert result.typename == "table"
        assert result.total_record_count == 0
        assert result.chunk_count == 0

    @pytest.mark.asyncio
    async def test_fetch_columns(
        self,
        mysql_activities: MySQLMetadataExtractionActivities,
        mock_activity_context: MagicMock,
    ) -> None:
        """Test column metadata extraction"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock column query results
        mysql_client = getattr(mysql_activities, "mysql_client")
        mysql_client.run_query.return_value = AsyncIteratorMock(
            [
                {
                    "column_name": "id",
                    "data_type": "int",
                    "is_nullable": "NO",
                    "column_key": "PRI",
                    "column_default": None,
                    "character_set_name": "utf8mb4",
                    "collation_name": "utf8mb4_unicode_ci",
                }
            ]
        )

        # Execute column extraction
        result = await mysql_activities.fetch_columns(workflow_config)

        # Verify result structure
        assert result is not None
        assert isinstance(result, ActivityStatistics)
        assert result.typename == "column"
        assert result.total_record_count == 0
        assert result.chunk_count == 0

    @pytest.mark.asyncio
    async def test_fetch_procedures(
        self,
        mysql_activities: MySQLMetadataExtractionActivities,
        mock_activity_context: MagicMock,
    ) -> None:
        """Test procedure metadata extraction"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock procedure query results
        mysql_client = getattr(mysql_activities, "mysql_client")
        mysql_client.run_query.return_value = AsyncIteratorMock(
            [{"routine_name": "proc1", "routine_type": "PROCEDURE"}]
        )

        # Execute procedure extraction
        result = await mysql_activities.fetch_procedures(workflow_config)

        # Verify result structure
        assert result is not None
        assert isinstance(result, ActivityStatistics)
        assert result.typename == "extras-procedure"
        assert result.total_record_count == 0
        assert result.chunk_count == 0


class TestMySQLMetadataExtractionWorkflow:
    """Test MySQL metadata extraction workflow"""

    @pytest.mark.asyncio
    async def test_workflow_error_handling(
        self,
        mysql_workflow: MySQLMetadataExtractionWorkflow,
        mock_state_store: MagicMock,
    ) -> None:
        """Test workflow error handling"""
        # Create test workflow config
        workflow_config = {
            "workflow_id": "test-workflow",
            "connection_qualified_name": "default/mysql/test-connection",
            "output_path": "/tmp/test_output",
            "tenant_id": "test-tenant",
        }

        # Mock state store to raise an error
        mock_state_store.get_state.side_effect = Exception("Test error")

        # Execute workflow and verify error handling
        with pytest.raises(Exception):
            await mysql_workflow.run(workflow_config)
