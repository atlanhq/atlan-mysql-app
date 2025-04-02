import asyncio
import os

from application_sdk.application.fastapi import FastAPIApplication, HttpWorkflowTrigger
from application_sdk.clients.temporal import TemporalClient
from application_sdk.common.logger_adaptors import get_logger
from application_sdk.worker import Worker
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.activities.metadata_extraction.mysql import MySQLMetadataExtractionActivities
from app.clients import MySQLClient
from app.handlers import MySQLWorkflowHandler
from app.transformers.atlas import MySQLAtlasTransformer
from app.workflows.metadata_extraction.mysql import MySQLMetadataExtractionWorkflow

logger = get_logger(__name__)

ATLAN_APPLICATION_NAME = os.getenv("ATLAN_APPLICATION_NAME", "mysql")
ATLAN_APP_HOST = os.getenv("ATLAN_APP_HTTP_HOST", "0.0.0.0")
ATLAN_APP_PORT = int(os.getenv("ATLAN_APP_HTTP_PORT", 8000))
ATLAN_APP_DASHBOARD_HOST = os.getenv("ATLAN_APP_DASHBOARD_HTTP_HOST", "0.0.0.0")
ATLAN_APP_DASHBOARD_PORT = int(os.getenv("ATLAN_APP_DASHBOARD_HTTP_PORT", 8050))
ATLAN_TENANT_ID = os.getenv("ATLAN_TENANT_ID", "default")
ATLAN_TEMPORAL_UI_HOST = os.getenv("ATLAN_TEMPORAL_UI_HOST", "localhost")
ATLAN_TEMPORAL_UI_PORT = int(os.getenv("ATLAN_TEMPORAL_UI_PORT", 8233))
MAX_CONCURRENT_ACTIVITIES = int(os.getenv("ATLAN_MAX_CONCURRENT_ACTIVITIES", 5))

# Set up templates
templates = Jinja2Templates(directory="frontend/templates")


async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_dashboard_http_port": ATLAN_APP_DASHBOARD_PORT,
            "app_dashboard_http_host": ATLAN_APP_DASHBOARD_HOST,
            "app_http_port": ATLAN_APP_PORT,
            "app_http_host": ATLAN_APP_HOST,
            "tenant_id": ATLAN_TENANT_ID,
            "app_name": ATLAN_APPLICATION_NAME,
            "temporal_ui_host": ATLAN_TEMPORAL_UI_HOST,
            "temporal_ui_port": ATLAN_TEMPORAL_UI_PORT,
        },
    )


def setup_routes(app: FastAPIApplication):
    app.app.get("/")(home)
    # Mount static files
    app.app.mount("/", StaticFiles(directory="frontend/static"), name="static")


async def initialize_and_start():
    # Creating resources
    sql_client = MySQLClient()
    temporal_client = TemporalClient(application_name=ATLAN_APPLICATION_NAME)
    await temporal_client.load()

    # Creating controllers
    handler = MySQLWorkflowHandler(sql_client=sql_client)

    activities = MySQLMetadataExtractionActivities(
        sql_client_class=MySQLClient,
        handler_class=MySQLWorkflowHandler,
        transformer_class=MySQLAtlasTransformer,
    )

    # Creating workflow
    worker: Worker = Worker(
        temporal_client=temporal_client,
        workflow_classes=[MySQLMetadataExtractionWorkflow],
        temporal_activities=MySQLMetadataExtractionWorkflow.get_activities(activities),
        passthrough_modules=["application_sdk", "pandas", "os", "app"],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )

    # Creating FastAPI application
    fast_api_app = FastAPIApplication(
        handler=handler,
        temporal_client=temporal_client,
    )

    fast_api_app.register_workflow(
        MySQLMetadataExtractionWorkflow,
        triggers=[HttpWorkflowTrigger(endpoint="/start", methods=["POST"])],
    )
    # Setup routes
    setup_routes(fast_api_app)

    # Add more logging statements
    logger.info("Created application")
    logger.info(f"Starting worker on {ATLAN_APPLICATION_NAME}")
    await worker.start(daemon=True)
    logger.info("Worker started successfully")

    logger.info(f"Starting application on {ATLAN_APP_HOST}:{ATLAN_APP_PORT}")
    await fast_api_app.start(host=ATLAN_APP_HOST, port=ATLAN_APP_PORT)


if __name__ == "__main__":
    asyncio.run(initialize_and_start())
