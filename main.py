import asyncio
import logging
import threading
from contextlib import asynccontextmanager

import uvicorn
from application_sdk.app.rest import FastAPIApplicationBuilder
from application_sdk.workflows.resources.temporal_resource import (
    TemporalConfig,
    TemporalResource,
)
from application_sdk.workflows.sql.controllers.auth import SQLWorkflowAuthController
from application_sdk.workflows.sql.workflows.workflow import SQLWorkflow
from application_sdk.workflows.workers.worker import WorkflowWorker
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.workflow import (
    MysqlWorkflowBuilder,
    MysqlWorkflowMetadata,
    MysqlWorkflowPreflight,
    MysqlSQLResourceConfig,
    MysqlResource
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    atlan_app_builder.on_api_service_start()

    worker: WorkflowWorker = WorkflowWorker(
        temporal_resource=temporal_resource,
        temporal_activities=mysql_workflow.get_activities(),
        workflow_class=SQLWorkflow,
    )

    worker_thread = threading.Thread(
        target=lambda: asyncio.run(worker.start()), daemon=True
    )
    worker_thread.start()
    yield


app = FastAPI(title="MySQL App", lifespan=lifespan)

APPLICATION_NAME = "mysql-connector"

if __name__ == "__main__":
    sql_resource = MysqlResource(MysqlSQLResourceConfig())
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

    atlan_app_builder = FastAPIApplicationBuilder(
        app=app,
        resource=sql_resource,
        workflow=mysql_workflow,
        preflight_check_controller=MysqlWorkflowPreflight(sql_resource=sql_resource),
        metadata_controller=MysqlWorkflowMetadata(sql_resource=sql_resource),
        auth_controller=SQLWorkflowAuthController(sql_resource=sql_resource),
    )
    atlan_app_builder.add_telemetry_routes()
    atlan_app_builder.add_workflows_router()

    # always mount the frontend at the end
    app.mount("/", StaticFiles(directory="frontend", html=True), name="static")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )

    # atlan_app_builder.configure_open_telemetry()