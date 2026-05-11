"""Tier-4 full-DAG e2e test for the MySQL connector.

Runs against the tenant's full system-apps DAG (extract → qi → publish
→ lineage-app → lineage-publish). The connector code under test runs
in a CI-side docker compose worker (registered on a unique Temporal
queue named ``atlan-mysql-ci-<run_id>``); the AE workflow's extract
activity dispatches to that queue via ``agent-json.agent-name`` routing.
Worker writes raw + transformed artifacts to the shared tenant S3
bucket; the in-cluster publish app reads from the same bucket.

To run locally::

    # Bring up the compose stack first (worker + sibling mysql + Dapr).
    # In CI this is the SDR composite action with tier-4 overrides;
    # locally you'd run:
    #   docker compose \\
    #     -f ci-deploy/docker-compose.yaml \\
    #     -f .github/actions/sdr-e2e/docker-compose.ci.yml \\
    #     -f .github/e2e/tier-4-docker-compose.yaml \\
    #     up -d

    ATLAN_BASE_URL=https://devex.atlan.com \\
    ATLAN_API_KEY=... \\
    GITHUB_RUN_ID=$(date +%s) \\
    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=... \\
        uv run pytest tests/full_dag/ -v

The test class skips gracefully when the harness env isn't configured,
so it can sit alongside the per-PR tier-3 suite without breaking
unrelated pytest invocations.
"""

from __future__ import annotations

import os

import pytest

# The full-DAG harness module is v3-SDK-only — `BaseFullDAGE2ETest`
# requires the application_sdk testing package shipped in PR #1710.
# Skip the whole module when the SDK is older or the harness env
# isn't set; tier-3 tests sit in tests/sdr/ and are unaffected.
pytest.importorskip(
    "application_sdk.testing.full_dag",
    reason="full-DAG e2e tests require application-sdk PR #1710+",
)

if not os.environ.get("ATLAN_BASE_URL") or not os.environ.get("ATLAN_API_KEY"):
    pytest.skip(
        "ATLAN_BASE_URL + ATLAN_API_KEY not set; full-DAG e2e harness disabled",
        allow_module_level=True,
    )

from application_sdk.testing.full_dag import BaseFullDAGE2ETest, RunMode  # noqa: E402
from application_sdk.testing.full_dag.payload import (  # noqa: E402
    AgentSpec,
    DatabaseSpec,
)


class TestMySQLFullDAG(BaseFullDAGE2ETest):
    """Submit an AE workflow targeting our CI-side worker + assert in Atlas.

    Tier-4 specifics:
        - ``mode = RunMode.AGENT`` — connector runs in CI compose, not
          in a tenant-deployed pod. AE dispatches to our unique queue.
        - ``app_service_url`` is metadata-only in agent mode (Temporal
          handles dispatch); we set it to the tenant's prod URL anyway
          for diagnostic clarity in the AE workflow's stored payload.
        - ``database_spec()`` points at the sibling ``mysql:8.0`` brought
          up by the tier-4 compose overlay with the hermetic seed.sql
          dataset — three databases, ~20 rows total.
        - ``agent_spec()`` uses a unique agent-name keyed off ``run_id``
          so each CI run gets its own Temporal queue. The compose
          overlay sets ``ATLAN_DEPLOYMENT_NAME=ci-<run_id>`` on the
          worker so it registers on that same queue.
    """

    connector_short_name = "mysql"
    argo_package_name = "@atlan/mysql"
    argo_template_name = "atlan-mysql"
    mode = RunMode.AGENT
    app_service_url = "http://mysql.mysql-app.svc.cluster.local"

    # Keep these scenario-config attrs at the class level rather than
    # in env so the test stays deterministic across reruns of the same
    # GitHub Actions workflow run.
    connection_name_prefix = "tier-4-e2e"
    include_filter = '{"^def$":["^e2e_main$"]}'
    exclude_filter = "{}"
    connection_admin_users = ("aryaman",)
    connection_admin_roles = ("30502f8b-f748-4771-9b71-2a3b3b5faae0",)

    # Slightly tighter timeouts than the BaseFullDAGE2ETest defaults:
    # the hermetic seed dataset is small (~20 rows total) so extract +
    # publish complete in well under 10 min, and the AE poll loop
    # should hear back even faster.
    ae_poll_timeout_seconds = 600
    atlas_poll_timeout_seconds = 900

    def database_spec(self) -> DatabaseSpec:
        # `host=mysql` resolves over the compose default network to
        # the sibling mysql:8.0 the tier-4 overlay brings up. Username
        # and password match seed.sql's GRANT statements + the
        # MYSQL_USER/MYSQL_PASSWORD env on the mysql service.
        return DatabaseSpec(
            host="mysql",
            port=3306,
            username="e2e_user",
            password="e2e_pass",
            connector_config_name="atlan-connectors-mysql",
        )

    def agent_spec(self) -> AgentSpec:
        return AgentSpec(agent_name=f"ci-{self.run_id}")
