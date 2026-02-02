import asyncio

from application_sdk.application.metadata_extraction.sql import (
    BaseSQLMetadataExtractionApplication,
)
from application_sdk.constants import APPLICATION_NAME
from application_sdk.workflows.metadata_extraction.sql import (
    BaseSQLMetadataExtractionWorkflow,
)

from app.activities.metadata_extraction.mysql import (
    MySQLSQLMetadataExtractionActivities,
)
from app.clients import SQLClient
from app.handlers.mysql import MySQLHandler
from app.transformers.query import MySQLQueryBasedTransformer


async def main():
    # Initialize the application with MySQL-specific implementations
    # APPLICATION_NAME comes from application_sdk.constants (reads ATLAN_APPLICATION_NAME env var, defaults to "default")
    # For MySQL, set ATLAN_APPLICATION_NAME=mysql in .env or deployment config
    application = BaseSQLMetadataExtractionApplication(
        name=APPLICATION_NAME,
        client_class=SQLClient,
        handler_class=MySQLHandler,
        transformer_class=MySQLQueryBasedTransformer,  # type: ignore
    )

    # Setup the workflow with MySQL-specific activities
    # Using BaseSQLMetadataExtractionWorkflow directly - all customizations are in activities
    await application.setup_workflow(
        workflow_and_activities_classes=[
            (
                BaseSQLMetadataExtractionWorkflow,
                MySQLSQLMetadataExtractionActivities,
            ),
        ]
    )

    # Start the worker
    await application.start_worker()

    # Setup the application server
    # BaseSQLMetadataExtractionWorkflow is the default, but explicitly specified for clarity
    # has_configmap=True enables playground frontend (reads JSON configs from app/templates/)
    await application.setup_server(
        workflow_class=BaseSQLMetadataExtractionWorkflow, has_configmap=True
    )

    # Start the application server
    await application.start_server()


if __name__ == "__main__":
    asyncio.run(main())
