import asyncio
import traceback
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from application_sdk.workflows.sql.workflows.workflow import SQLWorkflow
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)


@workflow.defn
class MockSQLWorkflow(SQLWorkflow):
    @workflow.run
    async def run(self, workflow_args: Dict[str, Any]):
        workflow_id = workflow_args["workflow_id"]
        retry_policy = RetryPolicy(
            maximum_attempts=6,
            backoff_coefficient=2,
        )

        workflow_run_id = workflow.info().run_id
        output_prefix = workflow_args["output_prefix"]
        output_path = f"{output_prefix}/{workflow_id}/{workflow_run_id}"
        workflow_args["output_path"] = output_path

        fetch_and_transforms = [
            self.fetch_and_transform(self.fetch_databases, workflow_args, retry_policy),  # type: ignore
            self.fetch_and_transform(self.fetch_schemas, workflow_args, retry_policy),  # type: ignore
            self.fetch_and_transform(self.fetch_tables, workflow_args, retry_policy),  # type: ignore
            self.fetch_and_transform(self.fetch_columns, workflow_args, retry_policy),  # type: ignore
        ]

        await asyncio.gather(*fetch_and_transforms)

        workflow.logger.info(f"Extraction workflow completed for {workflow_id}")


@pytest.mark.asyncio
async def test_extraction_workflow():
    workflow_config = {
        "workflow_id": "test_workflow",
        "credential_guid": "credential_1234",
        "output_prefix": "/tmp/test_output",
        "connection": {"connection": "dev"},
        "metadata": {
            "exclude-filter": "{}",
            "include-filter": "{}",
            "temp-table-regex": "",
            "advanced-config-strategy": "default",
            "use-source-schema-filtering": "false",
            "use-jdbc-internal-methods": "true",
            "authentication": "BASIC",
            "extraction-method": "direct",
        },
    }

    mock_fetch_databases = MagicMock()
    mock_fetch_databases.return_value = [{"typename": "database", "chunk_count": 1}]

    mock_fetch_schemas = MagicMock()
    mock_fetch_schemas.return_value = [{"typename": "schema", "chunk_count": 1}]

    mock_fetch_tables = MagicMock()
    mock_fetch_tables.return_value = [{"typename": "table", "chunk_count": 1}]

    mock_fetch_columns = MagicMock()
    mock_fetch_columns.return_value = [{"typename": "column", "chunk_count": 1}]

    mock_transform_data = MagicMock()
    mock_transform_data.return_value = 1
    mock_write_type_metadata = MagicMock()
    mock_write_type_metadata.return_value = None

    @activity.defn(name="fetch_databases")
    async def wrapped_mock_fetch_databases(workflow_config: Dict[str, Any]):
        return mock_fetch_databases(workflow_config)

    @activity.defn(name="fetch_schemas")
    async def wrapped_mock_fetch_schemas(workflow_config: Dict[str, Any]):
        return mock_fetch_schemas(workflow_config)

    @activity.defn(name="fetch_tables")
    async def wrapped_mock_fetch_tables(workflow_config: Dict[str, Any]):
        return mock_fetch_tables(workflow_config)

    @activity.defn(name="fetch_columns")
    async def wrapped_mock_fetch_columns(workflow_config: Dict[str, Any]):
        return mock_fetch_columns(workflow_config)

    @activity.defn(name="transform_data")
    async def wrapped_mock_transform_data(workflow_args: Dict[str, Any]):
        return mock_transform_data(workflow_args)

    @activity.defn(name="write_type_metadata")
    async def wrapped_mock_write_type_metadata(
        workflow_args: Dict[str, Any],
    ):
        mock_write_type_metadata(workflow_args)

    try:
        env = await WorkflowEnvironment.start_local()
        async with Worker(
            env.client,
            task_queue="test_queue",
            workflows=[MockSQLWorkflow],
            activities=[
                wrapped_mock_fetch_databases,
                wrapped_mock_fetch_schemas,
                wrapped_mock_fetch_tables,
                wrapped_mock_fetch_columns,
                wrapped_mock_transform_data,
                wrapped_mock_write_type_metadata,
            ],
            workflow_runner=SandboxedWorkflowRunner(
                restrictions=SandboxRestrictions.default.with_passthrough_modules(
                    "application_sdk"
                )
            ),
        ):
            result: Any = await env.client.execute_workflow(  # pyright: ignore[reportUnknownMemberType]
                MockSQLWorkflow.run,  # type: ignore
                workflow_config,
                id="test_workflow",
                task_queue="test_queue",
            )

    except Exception as e:
        print(f"Error during workflow execution: {e}")
        print(f"Error type: {type(e)}")
        print(f"Error traceback: {traceback.format_exc()}")
        raise e

    assert result is None

    assert mock_fetch_databases.call_count == 1
    assert mock_fetch_schemas.call_count == 1
    assert mock_fetch_tables.call_count == 1
    assert mock_fetch_columns.call_count == 1
