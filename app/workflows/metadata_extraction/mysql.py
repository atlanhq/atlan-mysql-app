from typing import Any, Dict, Type

from application_sdk.workflows.metadata_extraction.sql import (
    BaseSQLMetadataExtractionWorkflow,
)
from temporalio import workflow

from app.activities.metadata_extraction.mysql import (
    MySQLSQLMetadataExtractionActivities,
)


@workflow.defn
class MySQLMetadataExtractionWorkflow(BaseSQLMetadataExtractionWorkflow):
    """
    Workflow for extracting metadata from MySQL
    """

    activities_cls: Type[MySQLSQLMetadataExtractionActivities] = (  # type: ignore
        MySQLSQLMetadataExtractionActivities
    )

    @workflow.run
    async def run(self, workflow_config: Dict[str, Any]) -> None:
        """Run the workflow.

        Args:
            workflow_config: The workflow arguments.
        """
        await super().run(workflow_config)
