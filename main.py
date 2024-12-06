import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager

from application_sdk.app.rest.fastapi import (
    FastAPIApplication,
    FastAPIApplicationConfig,
)
from application_sdk.workflows.resources.temporal_resource import (
    TemporalConfig,
    TemporalResource,
)
from application_sdk.workflows.sql.controllers.auth import SQLWorkflowAuthController
from application_sdk.workflows.sql.resources.sql_resource import SQLResourceConfig
from application_sdk.workflows.sql.workflows.workflow import SQLWorkflow
from application_sdk.workflows.workers.worker import WorkflowWorker
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.workflow import (
    MysqlResource,
    MysqlWorkflowBuilder,
    MysqlWorkflowMetadata,
    MysqlWorkflowPreflight,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await fastapi_app.on_app_start()

    worker: WorkflowWorker = WorkflowWorker(
        temporal_resource=temporal_resource,
        temporal_activities=mysql_workflow.get_activities(),
        workflow_classes=[SQLWorkflow],
    )

    worker_thread = threading.Thread(
        target=lambda: asyncio.run(worker.start()), daemon=True
    )
    worker_thread.start()
    yield


APPLICATION_NAME = "mysql-connector"
APP_PORT = int(os.getenv("APP_HTTP_PORT", 8000))
APP_HOST = os.getenv("APP_HTTP_HOST", "0.0.0.0")
APP_DASHBOARD_PORT = int(os.getenv("APP_DASHBOARD_HTTP_PORT", 8050))
APP_DASHBOARD_HOST = os.getenv("APP_DASHBOARD_HTTP_HOST", "0.0.0.0")

if __name__ == "__main__":
    sql_resource = MysqlResource(SQLResourceConfig())
    temporal_resource = TemporalResource(
        TemporalConfig(
            application_name=APPLICATION_NAME,
        )
    )
    asyncio.run(temporal_resource.load())

    mysql_workflow: SQLWorkflow = (
        MysqlWorkflowBuilder()
        .set_sql_resource(sql_resource=sql_resource)
        .set_temporal_resource(temporal_resource=temporal_resource)
        .build()
    )

    # Creating FastAPI application
    fastapi_app = FastAPIApplication(
        auth_controller=SQLWorkflowAuthController(sql_resource=sql_resource),
        metadata_controller=MysqlWorkflowMetadata(sql_resource=sql_resource),
        preflight_check_controller=MysqlWorkflowPreflight(sql_resource=sql_resource),
        workflow=mysql_workflow,
        config=FastAPIApplicationConfig(
            host=APP_HOST,
            port=APP_PORT,
            lifespan=lifespan,
        ),
    )
    fastapi_app.app.mount(
        "/", StaticFiles(directory="frontend", html=True), name="static"
    )

    # Starting FastAPI application
    asyncio.run(fastapi_app.start())

    # atlan_app_builder.configure_open_telemetry()
