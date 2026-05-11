"""SDR integration tests for the MySQL connector.

Validates the connector running inside a customer-style SDR container
(built by atlan-configurator + docker compose) rather than the local
Dapr + Temporal + direct-Python stack used by tests/e2e/.

The API surface is identical — same endpoints, same request shapes — so
most scenarios mirror tests/e2e/. The key differences:

* No external MySQL: the compose overlay at
  ``.github/e2e/docker-compose.ci.yml`` brings up a ``mysql:8.0``
  container seeded by ``.github/e2e/seed.sql`` on the same compose
  network. Tests connect via service DNS (``host=mysql``, ``port=3306``).

* No local Temporal: the container connects to the test tenant's
  Temporal. Workflow-completion polling uses the container's HTTP status
  endpoint (``GET /workflows/v1/status/{wf}/{run}``).

* Output path: the container's Dapr objectstore uses
  ``bindings.localstorage`` with ``rootPath=/app/data`` (see
  ``test-config.yaml.tmpl`` in the SDK action). The compose mount makes
  artifacts available on the host under
  ``data/artifacts/apps/mysql/workflows/<wf>/<run>/raw/``.

Prerequisites
-------------
The SDR container must already be running on ``localhost:8000`` when
these tests execute. The CI workflow handles this — local runs can use
``docker compose -f ci-deploy/docker-compose.yaml \\
    -f .github/actions/sdr-e2e/docker-compose.ci.yml \\
    -f .github/e2e/docker-compose.ci.yml up -d`` after generating
``ci-deploy/`` via atlan-configurator.

Credentials are CI-only constants pinned in
``.github/e2e/docker-compose.ci.yml`` (the mysql:8.0 image's
``MYSQL_USER``/``MYSQL_PASSWORD``) and ``.github/e2e/make-secrets.py``
(the secret-store bundle). No repo-level secrets are needed.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

# application_sdk.testing.sdr is v3-only. The SDR e2e harness runs in a
# v3-SDK environment where the import resolves; locally outside that
# stack, pytest skips the module instead of failing collection.
pytest.importorskip(
    "application_sdk.testing.sdr",
    reason="SDR e2e tests require application-sdk v3+",
)

from application_sdk.testing.integration import (  # noqa: E402
    Scenario,
    equals,
    is_dict,
    is_list,
    is_not_empty,
    is_string,
)
from application_sdk.testing.sdr import BaseSDRIntegrationTest  # noqa: E402

# Hardcoded compose-side constants. These intentionally do NOT come from
# env vars — the SDR stack is hermetic, so the same values are baked into
# docker-compose.ci.yml, make-secrets.py, and here. Diverging any of the
# three will surface as auth or preflight failures in CI immediately.
_MYSQL_HOST = "mysql"
_MYSQL_PORT = 3306
_MYSQL_DATABASE = "e2e_main"
_MYSQL_USERNAME = "e2e_user"
_MYSQL_PASSWORD = "e2e_pass"

# agent_json used for SDR workflow credential resolution. Username and
# password are ref-keys resolved from the Dapr local.file secret store
# (secretstore component → /app/secrets/credentials.json under
# secret-path "mysql-credentials").
_AGENT_JSON: Dict[str, Any] = {
    "agent-name": "mysql-ci-agent",
    "secret-manager": "local",
    "secret-path": "mysql-credentials",
    "auth-type": "basic",
    "host": _MYSQL_HOST,
    "port": _MYSQL_PORT,
    "basic.username": "username",
    "basic.password": "password",
    "extra.database": _MYSQL_DATABASE,
}

_valid_creds_base: Dict[str, Any] = {
    "username": _MYSQL_USERNAME,
    "password": _MYSQL_PASSWORD,
    "host": _MYSQL_HOST,
    "port": _MYSQL_PORT,
    "authType": "basic",
    "type": "all",
    "extra": {"database": _MYSQL_DATABASE},
}

# Configurator-generated objectstore writes to /app/data inside the
# container; the SDK compose mounts ./data on the host to that path so
# artifacts surface here.
_SDR_OUTPUT_BASE = "data/artifacts/apps/mysql/workflows"


class TestMySQLSdr(BaseSDRIntegrationTest):
    """MySQL SDR integration suite — auth / preflight / workflow.

    Runs against the connector inside the SDR docker compose stack with
    a sibling ``mysql:8.0`` service seeded from
    ``.github/e2e/seed.sql``. Workflow-completion polling and
    agent-credential routing come from ``BaseSDRIntegrationTest``.
    """

    timeout: int = 180
    agent_spec_template = _AGENT_JSON

    default_credentials: Dict[str, Any] = dict(_valid_creds_base)

    default_metadata: Dict[str, Any] = {
        "exclude-filter": "{}",
        "include-filter": json.dumps({f"^{_MYSQL_DATABASE}$": []}),
        "temp-table-regex": "",
        "extraction-method": "direct",
    }

    default_connection: Dict[str, Any] = {
        "connection_name": "test_mysql_sdr",
        "connection_qualified_name": "default/mysql/sdr_test",
    }

    scenarios = [
        # =====================================================================
        # Auth
        # =====================================================================
        Scenario(
            name="auth_valid_credentials",
            api="auth",
            assert_that={
                "success": equals(True),
                "data.status": equals("success"),
            },
            description="Valid credentials authenticate via the SDR container",
        ),
        Scenario(
            name="auth_response_structure",
            api="auth",
            assert_that={
                "success": equals(True),
                "data": is_dict(),
                "data.status": is_string(),
                "data.message": is_string(),
                "data.identities": is_list(),
            },
            description="Auth response has the expected v3 shape",
        ),
        Scenario(
            name="auth_invalid_credentials",
            api="auth",
            credentials={
                **_valid_creds_base,
                "username": "definitely_not_a_user",
                "password": "definitely_not_a_password",
            },
            assert_that={
                "success": equals(False),
                "data.status": equals("failed"),
            },
            description="Wrong credentials fail authentication",
        ),
        Scenario(
            name="auth_wrong_host",
            api="auth",
            credentials={
                **_valid_creds_base,
                "host": "nonexistent-mysql-host.invalid",
            },
            assert_that={
                "success": equals(False),
                "data.status": equals("failed"),
            },
            description="Unreachable host fails authentication",
        ),
        # =====================================================================
        # Preflight
        # ---------------------------------------------------------------------
        # The SDK's preflight service wraps PreflightOutput's checks list
        # into camelCase top-level keys on data (see
        # application_sdk.handler.service.preflight_check — each
        # PreflightCheck.name becomes a key, value is
        # {success, message}). mysql's handler emits checks named
        # "auth" and "connectivity" → data.auth / data.connectivity
        # in the response.
        # =====================================================================
        Scenario(
            name="preflight_valid_configuration",
            api="preflight",
            assert_that={
                "success": equals(True),
                "data.auth.success": equals(True),
                "data.connectivity.success": equals(True),
            },
            description="Valid configuration passes auth + connectivity preflight checks",
        ),
        Scenario(
            name="preflight_invalid_credentials",
            api="preflight",
            credentials={**_valid_creds_base, "password": "definitely_wrong"},
            assert_that={
                "success": equals(False),
                "data.auth.success": equals(False),
                "data.auth.message": is_string(),
            },
            description="Invalid credentials fail the auth preflight check",
        ),
        # =====================================================================
        # Full workflow + output validation
        # ---------------------------------------------------------------------
        # _execute_scenario polls GET /workflows/v1/status/{wf}/{run}
        # until COMPLETED or workflow_timeout seconds elapse. Seed dataset
        # is tiny (~20 rows across 3 dbs) so the workflow runs end-to-end
        # in well under the budget.
        #
        # Temporal namespace authz on the OAuth client is via the
        # temporal-app-permissions-scope client scope on Keycloak —
        # injects ["default:read","default:write"] under the `permissions`
        # claim that Temporal's default claim mapper reads.
        # =====================================================================
        Scenario(
            name="workflow_include_main_db",
            api="workflow",
            metadata={
                "exclude-filter": "{}",
                "include-filter": json.dumps({f"^{_MYSQL_DATABASE}$": []}),
                "temp-table-regex": "",
                "extraction-method": "agent",
            },
            assert_that={
                "success": equals(True),
                "data.workflow_id": is_not_empty(),
                "data.run_id": is_not_empty(),
            },
            extracted_output_base_path=_SDR_OUTPUT_BASE,
            workflow_timeout=300,
            polling_interval=10,
            description=(
                "Full SDR workflow runs to COMPLETED on tenant Temporal "
                "with include-filter pinned to the seed DB"
            ),
        ),
        Scenario(
            name="workflow_mixed_filters",
            api="workflow",
            metadata={
                "exclude-filter": '{"^e2e_excluded$":[]}',
                "include-filter": '{".*": []}',
                "temp-table-regex": "",
                "extraction-method": "agent",
            },
            assert_that={
                "success": equals(True),
                "data.workflow_id": is_not_empty(),
                "data.run_id": is_not_empty(),
            },
            extracted_output_base_path=_SDR_OUTPUT_BASE,
            workflow_timeout=300,
            polling_interval=10,
            description=(
                "Mixed include + exclude filters — excludes the legacy "
                "schema, includes the other two seeded databases"
            ),
        ),
    ]
