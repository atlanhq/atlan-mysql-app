"""E2E test: full ETL pipeline — Extract, Transform, Publish to Atlan.

Runs the complete pipeline against a deployed MySQL app:
  1. Create a test Connection via pyatlan with unique name
  2. Run E&T workflow (extract MySQL metadata, transform to Atlas entities)
  3. Trigger PublishWorkflow on publish-app
  4. Verify entities are published to Atlan (databases, schemas, tables, columns)
  5. Cleanup: delete test connection

Prerequisites:
  - App deployed to K8s (or port-forwarded locally)
  - Temporal accessible from the test runner
  - ATLAN_API_KEY, ATLAN_BASE_URL, CREDENTIAL_GUID env vars set
  - Publish-app deployed and running in the cluster

Run with:
  source .env && make test-e2e-remote
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from typing import Any

import pytest
import requests as http_requests
from pyatlan.client.atlan import AtlanClient
from pyatlan.model.assets import Asset, Connection
from pyatlan.model.enums import AtlanConnectorType
from pyatlan.model.fluent_search import FluentSearch

logger = logging.getLogger("e2e")

# ── Configuration from environment ──────────────────────────────────────────

APP_NAME = "mysql"
APP_HOST = os.getenv("APP_BASE_URL", "http://localhost:8000")
TEMPORAL_SERVER_URL = os.getenv("TEMPORAL_SERVER_URL", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
CREDENTIAL_GUID = os.getenv(
    "CREDENTIAL_GUID",
    os.getenv("REMOTE_CREDENTIAL_GUID", ""),
)
ATLAN_API_KEY = os.getenv("ATLAN_API_KEY", "")
ATLAN_BASE_URL = os.getenv("ATLAN_BASE_URL", "")

PUBLISH_TASK_QUEUE = "atlan-publish-production"
PUBLISH_WORKFLOW_TYPE = "PublishWorkflow"
PUBLISH_TIMEOUT = 600
ET_TIMEOUT = 300

# ── Skip if not configured ──────────────────────────────────────────────────

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (CREDENTIAL_GUID and ATLAN_API_KEY and ATLAN_BASE_URL),
        reason="Publish integration requires CREDENTIAL_GUID, ATLAN_API_KEY, ATLAN_BASE_URL",
    ),
]

_workflow_state: dict[str, str] = {}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_unique(prefix: str) -> str:
    """Generate a unique name like TestId.make_unique."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _build_connection_entity(
    connection_qn: str, connection_name: str
) -> dict[str, Any]:
    return {
        "typeName": "Connection",
        "attributes": {
            "qualifiedName": connection_qn,
            "name": connection_name,
            "connectorName": "mysql",
            "category": "warehouse",
            "adminGroups": [],
            "adminUsers": [],
            "adminRoles": [],
        },
    }


def _build_publish_payload(
    connection_qn: str,
    connection_name: str,
    transformed_data_prefix: str,
) -> dict[str, Any]:
    return {
        "connection_qualified_name": connection_qn,
        "transformed_data_prefix": transformed_data_prefix,
        "publish_state_prefix": (
            f"persistent-artifacts/apps/atlan-publish-app/state/{connection_qn}/publish-state"
        ),
        "current_state_prefix": f"argo-artifacts/{connection_qn}/current-state",
        "delete_percentage_circuit_breaker": 80,
        "legacy_diff_count": {},
        "connection_entity": _build_connection_entity(connection_qn, connection_name),
        "executor_enabled": True,
        "connection_creation_enabled": False,
        "typedef_resolution_mode": "pyatlan_only",
        "enable_ars": False,
        "ars_data_prefix": "",
        "staging_data_prefix": (
            f"persistent-artifacts/apps/atlan-publish-app/state/{connection_qn}"
        ),
    }


# ── Temporal subprocess helper ──────────────────────────────────────────────

_TEMPORAL_SCRIPT = """\
import asyncio, json, sys
from temporalio.client import Client, WorkflowExecutionStatus

async def main():
    action = sys.argv[1]
    server_url = sys.argv[2]
    namespace = sys.argv[3]

    client = await Client.connect(server_url, namespace=namespace)

    if action == "start":
        wf_type = sys.argv[4]
        task_queue = sys.argv[5]
        wf_id = sys.argv[6]
        payload = json.loads(sys.argv[7])
        handle = await client.start_workflow(wf_type, payload, id=wf_id, task_queue=task_queue)
        print(json.dumps({"run_id": handle.first_execution_run_id}))

    elif action == "status":
        wf_id = sys.argv[4]
        handle = client.get_workflow_handle(wf_id)
        desc = await handle.describe()
        status = WorkflowExecutionStatus(
            desc.raw_description.workflow_execution_info.status
        ).name
        print(json.dumps({"status": status}))

asyncio.run(main())
"""


def _temporal_cmd(action: str, *args: str) -> dict:
    cmd = [
        sys.executable,
        "-c",
        _TEMPORAL_SCRIPT,
        action,
        TEMPORAL_SERVER_URL,
        TEMPORAL_NAMESPACE,
        *args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Temporal subprocess failed: {result.stderr}")
    return json.loads(result.stdout.strip())


def _submit_and_monitor_publish(
    publish_payload: dict[str, Any],
    workflow_id: str,
    timeout: int = PUBLISH_TIMEOUT,
) -> str:
    payload_json = json.dumps(publish_payload)
    start_result = _temporal_cmd(
        "start",
        PUBLISH_WORKFLOW_TYPE,
        PUBLISH_TASK_QUEUE,
        workflow_id,
        payload_json,
    )
    logger.info("PublishWorkflow submitted: run_id=%s", start_result["run_id"])

    deadline = time.time() + timeout
    while time.time() < deadline:
        status_result = _temporal_cmd("status", workflow_id)
        status = status_result["status"]
        logger.info("Publish workflow status: %s", status)
        if status in ("COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"):
            return status
        time.sleep(10)

    return "TIMED_OUT"


def _poll_workflow(workflow_id: str, run_id: str, timeout: int = ET_TIMEOUT) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = http_requests.get(
            f"{APP_HOST}/workflows/v1/status/{workflow_id}/{run_id}",
            timeout=30,
        )
        if resp.status_code == 200:
            status = resp.json().get("data", {}).get("status", "")
            logger.info("E&T workflow status: %s", status)
            if status in ("COMPLETED", "FAILED", "CANCELLED", "TERMINATED"):
                return status
        time.sleep(5)
    return "TIMED_OUT"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def atlan_client():
    return AtlanClient(base_url=ATLAN_BASE_URL, api_key=ATLAN_API_KEY)


@pytest.fixture(scope="module")
def connection_info(atlan_client):
    """Create a test MySQL connection via pyatlan with unique name."""
    unique_name = _make_unique("mysql-e2e")
    logger.info("Creating test connection: %s", unique_name)

    admin_role_guid = atlan_client.role_cache.get_id_for_name("$admin")
    assert admin_role_guid, "Admin role not found"

    connection = Connection.creator(
        name=unique_name,
        connector_type=AtlanConnectorType.MYSQL,
        admin_roles=[admin_role_guid],
        client=atlan_client,
    )
    response = atlan_client.asset.save(connection)
    created = response.assets_created(asset_type=Connection)[0]
    logger.info(
        "Connection created: name=%s qn=%s guid=%s",
        unique_name,
        created.qualified_name,
        created.guid,
    )

    yield {
        "name": unique_name,
        "qualified_name": created.qualified_name,
        "guid": created.guid,
    }

    # Cleanup
    logger.info("Deleting test connection: %s", created.qualified_name)
    try:
        atlan_client.asset.purge_by_guid(created.guid)
        logger.info("Connection deleted: %s", created.qualified_name)
    except Exception:
        logger.exception("Failed to delete connection: %s", created.qualified_name)


# ── Tests (ordered) ────────────────────────────────────────────────────────


@pytest.mark.order(1)
def test_health_check():
    resp = http_requests.get(f"{APP_HOST}/server/health", timeout=10)
    assert resp.status_code == 200


@pytest.mark.order(2)
def test_run_et_workflow(connection_info):
    """Run Extract & Transform workflow with real connection."""
    payload = {
        "credential_guid": CREDENTIAL_GUID,
        "metadata": {},
        "connection": {
            "typeName": "Connection",
            "attributes": {
                "qualifiedName": connection_info["qualified_name"],
                "name": connection_info["name"],
                "connectorName": "mysql",
                "category": "warehouse",
            },
            "connection_name": connection_info["name"],
            "connection_qualified_name": connection_info["qualified_name"],
        },
    }
    resp = http_requests.post(
        f"{APP_HOST}/workflows/v1/start",
        json=payload,
        timeout=60,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    workflow_id = data["data"]["workflow_id"]
    run_id = data["data"]["run_id"]
    logger.info("E&T started: workflow_id=%s run_id=%s", workflow_id, run_id)

    status = _poll_workflow(workflow_id, run_id)
    assert status == "COMPLETED", f"E&T workflow ended with: {status}"

    _workflow_state["workflow_id"] = workflow_id
    _workflow_state["run_id"] = run_id
    logger.info("E&T completed: %s", workflow_id)


@pytest.mark.order(3)
def test_trigger_publish_workflow(connection_info):
    """Trigger PublishWorkflow and wait for completion."""
    workflow_id = _workflow_state.get("workflow_id")
    run_id = _workflow_state.get("run_id")
    assert workflow_id, "E&T must complete first"

    transformed_data_prefix = (
        f"artifacts/apps/{APP_NAME}/workflows/{workflow_id}/{run_id}/transformed"
    )
    logger.info("Transformed data prefix: %s", transformed_data_prefix)

    publish_payload = _build_publish_payload(
        connection_qn=connection_info["qualified_name"],
        connection_name=connection_info["name"],
        transformed_data_prefix=transformed_data_prefix,
    )

    publish_wf_id = f"publish-mysql-{uuid.uuid4().hex[:16]}"
    status = _submit_and_monitor_publish(publish_payload, publish_wf_id)

    assert status == "COMPLETED", f"PublishWorkflow ended with: {status}"
    logger.info("Publish completed: %s", publish_wf_id)


@pytest.mark.order(4)
def test_verify_entities_in_atlan(connection_info, atlan_client):
    """Verify extracted MySQL entities are published to Atlan."""
    connection_qn = connection_info["qualified_name"]

    # Wait for Atlan to index published entities
    time.sleep(30)

    # Verify connection
    conn_results = list(
        atlan_client.asset.find_connections_by_name(
            connection_info["name"], connector_type="mysql"
        )
    )
    assert len(conn_results) >= 1, f"Connection not found: {connection_qn}"
    logger.info("Connection verified: %s", connection_qn)

    # Verify databases
    db_results = list(
        FluentSearch()
        .where(Asset.QUALIFIED_NAME.startswith(connection_qn))
        .where(Asset.TYPE_NAME.eq("Database"))
        .execute(client=atlan_client)
    )
    logger.info("Found %d databases under %s", len(db_results), connection_qn)
    assert len(db_results) >= 1, f"No databases under {connection_qn}"

    # Verify schemas
    schema_results = list(
        FluentSearch()
        .where(Asset.QUALIFIED_NAME.startswith(connection_qn))
        .where(Asset.TYPE_NAME.eq("Schema"))
        .execute(client=atlan_client)
    )
    logger.info("Found %d schemas", len(schema_results))
    assert len(schema_results) >= 1, f"No schemas under {connection_qn}"

    # Verify tables
    table_results = list(
        FluentSearch()
        .where(Asset.QUALIFIED_NAME.startswith(connection_qn))
        .where(Asset.TYPE_NAME.eq("Table"))
        .execute(client=atlan_client)
    )
    logger.info("Found %d tables", len(table_results))
    assert len(table_results) >= 1, f"No tables under {connection_qn}"

    # Verify columns
    column_results = list(
        FluentSearch()
        .where(Asset.QUALIFIED_NAME.startswith(connection_qn))
        .where(Asset.TYPE_NAME.eq("Column"))
        .execute(client=atlan_client)
    )
    logger.info("Found %d columns", len(column_results))
    assert len(column_results) >= 1, f"No columns under {connection_qn}"

    # Summary report
    logger.info("=" * 55)
    logger.info("PUBLISH VERIFICATION REPORT")
    logger.info("=" * 55)
    logger.info("Connection: %s", connection_qn)
    logger.info("Databases:  %d", len(db_results))
    logger.info("Schemas:    %d", len(schema_results))
    logger.info("Tables:     %d", len(table_results))
    logger.info("Columns:    %d", len(column_results))
    logger.info("=" * 55)
