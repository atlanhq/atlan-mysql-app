import asyncio

from application_sdk.application.metadata_extraction.sql import (
    BaseSQLMetadataExtractionApplication,
)

from app.activities.metadata_extraction.mysql import (
    MySQLSQLMetadataExtractionActivities,
)
from app.clients import SQLClient
from app.constants import APPLICATION_NAME
from app.handlers.mysql import MySQLHandler
from app.transformers.query import MySQLQueryBasedTransformer
from app.workflows.metadata_extraction.mysql import MySQLMetadataExtractionWorkflow


async def main():
    # Initialize the application with MySQL-specific implementations
    application = BaseSQLMetadataExtractionApplication(
        name=APPLICATION_NAME,
        client_class=SQLClient,
        handler_class=MySQLHandler,
        transformer_class=MySQLQueryBasedTransformer,  # type: ignore
    )

    # Setup the workflow with MySQL-specific workflow and activities
    await application.setup_workflow(
        workflow_and_activities_classes=[
            (
                MySQLMetadataExtractionWorkflow,
                MySQLSQLMetadataExtractionActivities,
            ),
        ]
    )

    # Start the worker
    await application.start_worker()

    # Setup the application server
    await application.setup_server(
        workflow_class=MySQLMetadataExtractionWorkflow, has_configmap=False
    )

    # Start the application server
    await application.start_server()


if __name__ == "__main__":
    asyncio.run(main())
