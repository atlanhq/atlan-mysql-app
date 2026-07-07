"""SDR integration tests for the MySQL connector.

Runs the connector inside a customer-style SDR container (atlan-configurator
+ docker compose, Dapr embedded, Temporal on the CI test tenant) rather than
the local testcontainer + direct-Python stack used by tests/integration/.

The stack is **self-contained**: ``.github/e2e/docker-compose.ci.yml`` brings
up a sibling ``mysql:8.0`` seeded from the same hermetic
``.github/e2e/seed.sql`` the full-DAG e2e uses, so the auth + extraction
scenarios run on every PR with no external database.

Source (from seed.sql / the compose ``mysql`` service)::

    host=mysql  port=3306  user=e2e_user  pass=e2e_pass
    databases: e2e_main (customers, orders, v_customer_order_totals),
               e2e_other, e2e_excluded

Output: the container's Dapr objectstore uses ``bindings.localstorage`` with
``rootPath=/data/storage``, mounted ``./data`` on the host, so workflow
artifacts land at ``data/artifacts/apps/mysql/workflows/<wf>/<run>/``.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from application_sdk.testing.integration import Scenario, equals, is_not_empty
from application_sdk.testing.sdr import BaseSDRIntegrationTest

# Sibling mysql service brought up by .github/e2e/docker-compose.ci.yml.
# Overridable via env so the suite can also target an external MySQL.
_MYSQL_HOST = os.environ.get("E2E_MYSQL_HOST", "mysql")
_port_env = os.environ.get("E2E_MYSQL_PORT", "3306")
_MYSQL_PORT = int(_port_env) if _port_env.isdigit() else 3306
_MYSQL_USER = os.environ.get("E2E_MYSQL_USERNAME", "e2e_user")
_MYSQL_PASSWORD = os.environ.get("E2E_MYSQL_PASSWORD", "e2e_pass")
_MYSQL_DB = os.environ.get("E2E_MYSQL_DATABASE", "e2e_main")

# agent_json for SDR workflow credential resolution. username/password are
# ref-keys resolved from the Dapr local.file secret store (secretstore
# component → /app/secrets/credentials.json, written by make-secrets.py).
_AGENT_JSON: Dict[str, Any] = {
    "agent-name": "mysql-ci-agent",
    "secret-manager": "local",
    "secret-path": "mysql-credentials",
    "auth-type": "basic",
    "host": _MYSQL_HOST,
    "port": _MYSQL_PORT,
    "basic.username": "username",
    "basic.password": "password",
    "extra.database": _MYSQL_DB,
}

_valid_creds_base: Dict[str, Any] = {
    "authType": "basic",
    "username": _MYSQL_USER,
    "password": _MYSQL_PASSWORD,
    "host": _MYSQL_HOST,
    "port": _MYSQL_PORT,
    "type": "all",
    "extra": {"database": _MYSQL_DB},
}

# The extraction scenario submits a workflow to the CI test tenant's
# Temporal, so it needs the SDR tenant secrets. Skip (rather than fail) when
# they're absent so the self-contained auth scenarios still validate the
# stack on a repo that hasn't had the SDR tenant secrets wired yet.
_TENANT_CONFIGURED = bool(os.environ.get("SDR_TEST_TENANT", "").strip())

# SDR objectstore output lands in ./data (localstorage rootPath=/data/storage,
# mounted ./data:/data/storage via docker compose).
_SDR_OUTPUT_BASE = "data/artifacts/apps/mysql/workflows"


class TestMySQLSdr(BaseSDRIntegrationTest):
    """MySQL SDR integration suite — auth + full extraction.

    Runs against the connector inside the SDR docker compose stack with a
    seeded sibling MySQL. Workflow-completion polling and agent-credential
    routing come from BaseSDRIntegrationTest.
    """

    timeout: int = 180
    agent_spec_template = _AGENT_JSON
    default_credentials: Dict[str, Any] = {
        "authType": "basic",
        "type": "all",
    }

    # Empty include-filter = crawl every seeded database (matches
    # tests/integration/test_mysql_workflow.py, which uses include_filter="").
    # extraction-method=agent routes credential resolution through the Dapr
    # secret store at secret-path.
    default_metadata: Dict[str, Any] = {
        "include-filter": "",
        "exclude-filter": "",
        "temp-table-regex": "",
        "extraction-method": "agent",
    }

    # Nested Connection wire shape so extracted assets carry the connection
    # qualifiedName prefix the assets-landed guard checks. A flat
    # {connection_qualified_name: ...} dict leaves attributes.qualifiedName
    # empty, dropping the prefix from every asset.
    default_connection: Dict[str, Any] = {
        "typeName": "Connection",
        "attributes": {
            "qualifiedName": "default/mysql/sdr_test",
            "name": "test_mysql_sdr",
        },
    }

    scenarios = [
        # =====================================================================
        # Auth
        # =====================================================================
        Scenario(
            name="auth_valid_credentials",
            api="auth",
            credentials=_valid_creds_base,
            assert_that={"success": equals(True)},
            description="Valid credentials authenticate against the seeded MySQL",
        ),
        Scenario(
            name="auth_invalid_credentials",
            api="auth",
            credentials={
                **_valid_creds_base,
                "username": "definitely_not_a_user",
                "password": "definitely_not_a_password",
            },
            assert_that={"success": equals(False)},
            description="Wrong credentials fail authentication",
        ),
        # =====================================================================
        # Full extraction + output validation (assets-landed guard)
        # =====================================================================
        Scenario(
            name="workflow_extraction_lands_assets",
            api="workflow",
            skip=not _TENANT_CONFIGURED,
            skip_reason=(
                "Set SDR_TEST_TENANT / SDR_CLIENT_ID / SDR_CLIENT_SECRET "
                "(CI test tenant) to run the extraction workflow against tenant "
                "Temporal. The seeded sibling MySQL needs no external secret."
            ),
            assert_that={
                "success": equals(True),
                "data.workflow_id": is_not_empty(),
                "data.run_id": is_not_empty(),
            },
            extracted_output_base_path=_SDR_OUTPUT_BASE,
            workflow_timeout=300,
            polling_interval=10,
            description=(
                "Full SDR extraction runs to COMPLETED on tenant Temporal and "
                "the extracted assets land in the container objectstore under "
                "the connection prefix (assets-landed guard, application-sdk#2552)"
            ),
        ),
    ]
