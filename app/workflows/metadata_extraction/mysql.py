import asyncio
import os
from datetime import timedelta
from typing import Any, Callable, Coroutine, Dict, List, Type, cast

from application_sdk.common.logger_adaptors import get_logger
from application_sdk.inputs.statestore import StateStoreInput
from application_sdk.workflows.metadata_extraction.sql import (
    SQLMetadataExtractionActivities,
    SQLMetadataExtractionWorkflow,
)
from temporalio import workflow
from temporalio.common import RetryPolicy

from app.activities.metadata_extraction.mysql import MySQLMetadataExtractionActivities

logger = get_logger(__name__)

DEFAULT_HEARTBEAT_TIMEOUT = timedelta(
    seconds=int(os.getenv("ATLAN_HEARTBEAT_TIMEOUT", 120))  # 2 minutes
)
DEFAULT_START_TO_CLOSE_TIMEOUT = timedelta(
    seconds=int(os.getenv("ATLAN_START_TO_CLOSE_TIMEOUT", 2 * 60 * 60))  # 2 hours
)


@workflow.defn
class MySQLMetadataExtractionWorkflow(SQLMetadataExtractionWorkflow):
    """
    Workflow for extracting metadata from MySQL databases.

    This class extends SQLMetadataExtractionWorkflow to provide MySQL-specific
    workflow functionality.
    """

    # Set the activities class to MySQL-specific activities
    activities_cls: Type[SQLMetadataExtractionActivities] = cast(
        Type[SQLMetadataExtractionActivities], MySQLMetadataExtractionActivities
    )

    # Set default timeouts
    default_heartbeat_timeout = DEFAULT_HEARTBEAT_TIMEOUT
    default_start_to_close_timeout = DEFAULT_START_TO_CLOSE_TIMEOUT

    @workflow.run
    async def run(self, workflow_config: Dict[str, Any]) -> None:
        """
        Run the MySQL metadata extraction workflow.

        Args:
            workflow_config: Configuration for the workflow.
        """
        # Extract workflow configuration
        workflow_id = workflow_config["workflow_id"]
        workflow_args: Dict[str, Any] = StateStoreInput.extract_configuration(
            workflow_id
        )

        workflow_run_id = workflow.info().run_id
        workflow_args["workflow_run_id"] = workflow_run_id

        workflow.logger.info(f"Starting MySQL extraction workflow for {workflow_id}")
        retry_policy = RetryPolicy(
            maximum_attempts=6,
            backoff_coefficient=2,
        )

        output_prefix = workflow_args["output_prefix"]
        output_path = f"{output_prefix}/{workflow_id}/{workflow_run_id}"
        workflow_args["output_path"] = output_path

        # Execute preflight check
        await workflow.execute_activity_method(
            self.activities_cls.preflight_check,
            workflow_args,
            retry_policy=retry_policy,
            start_to_close_timeout=self.default_start_to_close_timeout,
            heartbeat_timeout=self.default_heartbeat_timeout,
        )

        # Execute fetch and transform tasks in parallel
        fetch_and_transforms = [
            self.fetch_and_transform(
                self.activities_cls.fetch_databases,
                workflow_args,
                retry_policy,
            ),
            self.fetch_and_transform(
                self.activities_cls.fetch_schemas,
                workflow_args,
                retry_policy,
            ),
            self.fetch_and_transform(
                self.activities_cls.fetch_tables,
                workflow_args,
                retry_policy,
            ),
            self.fetch_and_transform(
                self.activities_cls.fetch_columns,
                workflow_args,
                retry_policy,
            ),
            self.fetch_and_transform(
                cast(
                    Callable[..., Coroutine[Any, Any, Any]],
                    self.activities_cls.fetch_procedures,
                ),
                workflow_args,
                retry_policy,
            ),
        ]
        await asyncio.gather(*fetch_and_transforms)

        workflow.logger.info(f"MySQL extraction workflow completed for {workflow_id}")

    @staticmethod
    def get_activities(
        activities: SQLMetadataExtractionActivities,
    ) -> List[Callable[..., Any]]:
        """
        Get the activities for the MySQL metadata extraction workflow.

        Args:
            activities: The MySQL metadata extraction activities.

        Returns:
            List of activity methods to execute.
        """
        return [
            activities.preflight_check,
            activities.fetch_databases,
            activities.fetch_schemas,
            activities.fetch_tables,
            activities.fetch_columns,
            cast(Callable[..., Coroutine[Any, Any, Any]], activities.fetch_procedures),
            activities.transform_data,
        ]
