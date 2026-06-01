"""Full-DAG e2e test for the MySQL connector.

Runs against the tenant's full system-apps DAG (extract → qi → publish
→ lineage-app → lineage-publish). The connector code under test runs
in a CI-side docker compose worker (registered on a unique Temporal
queue named ``atlan-mysql-e2e-full-ci-<run_id>``); the AE workflow's
extract activity dispatches to that queue via ``agent-json.agent-name``
routing. Worker writes raw + transformed artifacts to the shared tenant
S3 bucket (via the /api/blobstorage OAuth proxy in CI); the in-cluster
publish app reads from the same bucket.

To run locally::

    ATLAN_BASE_URL=https://devex.atlan.com \\
    ATLAN_API_KEY=... \\
    SDR_OAUTH_CLIENT_ID=... SDR_OAUTH_CLIENT_SECRET=... \\
    GITHUB_RUN_ID=$(date +%s) \\
        uv run pytest tests/e2e/ -v

The test class skips gracefully when the harness env isn't configured,
so it can sit alongside the per-PR SDR integration suite without
breaking unrelated pytest invocations.
"""

from __future__ import annotations

import os

import pytest

# The full-DAG harness module is v3-SDK-only — ``SQLAppE2EFullTest``
# requires the application_sdk testing package shipped in PR #1710.
# Skip the whole module when the SDK is older or the harness env
# isn't set; the per-PR SDR integration tests sit in tests/sdr/ and
# are unaffected.
pytest.importorskip(
    "application_sdk.testing.full_dag",
    reason="full-DAG e2e tests require application-sdk PR #1710+",
)

if not os.environ.get("ATLAN_BASE_URL") or not os.environ.get("ATLAN_API_KEY"):
    pytest.skip(
        "Full-DAG e2e harness needs ATLAN_BASE_URL + ATLAN_API_KEY "
        "(SDR_OAUTH_CLIENT_ID/SECRET are optional, forwarded only to "
        "pyatlan asset queries — AE management still requires the API key)",
        allow_module_level=True,
    )

from application_sdk.testing.full_dag import RunMode, SQLAppE2EFullTest  # noqa: E402
from application_sdk.testing.full_dag.payload import DatabaseSpec  # noqa: E402


class TestMySQLFullDAG(SQLAppE2EFullTest):
    """Submit an AE workflow targeting our CI-side worker + assert in Atlas.

    Inherits ``agent_spec`` (unique-per-run AGENT mode identity),
    ``connection_spec`` (``$admin`` role injected onto adminRoles via
    pyatlan), and the full-DAG mechanics from
    :class:`SQLAppE2EFullTest`. Only the connector-specific knobs and
    the sibling-DB ``database_spec`` live here.
    """

    connector_short_name = "mysql"
    argo_package_name = "@atlan/mysql"
    argo_template_name = "atlan-mysql"
    mode = RunMode.AGENT
    app_service_url = "http://mysql.mysql-app.svc.cluster.local"

    connection_name_prefix = "e2e-full-ci"
    # MySQL's SQL templates substitute include-filter into a literal
    # MySQL ``REGEXP '…'`` clause, so it expects an anchored regex
    # string (not the v3 dict-shape JSON the harness defaults to —
    # that crashes the server with pymysql 3688). Catalog is hardcoded
    # to ``def`` for MySQL.
    include_filter = r"^def\.e2e_main$"
    exclude_filter = ""
    # mysql v3 bundles view definitions into the main transformed
    # output rather than a dedicated ``view_data_prefix`` subfolder;
    # point QI at the right field so it doesn't fail jsonpath
    # resolution.
    qi_input_prefix_field = "transformed_data_prefix"

    # Poll knobs sized for devex — lineage-app + lineage-publish can
    # sit Running 30+ min when the tenant's queues are deep. GH job
    # timeout-minutes in the workflow is bumped to 120 in lockstep.
    ae_poll_interval_seconds = 60
    ae_poll_timeout_seconds = 5400
    atlas_poll_interval_seconds = 60
    atlas_poll_timeout_seconds = 1800

    # Atlas inventory floors for the hermetic seed.sql under
    # include_filter=e2e_main: one DB, one schema (`def`), two tables
    # (customers + orders), one view (v_customer_order_totals),
    # 4+4+3=11 columns. Conservative bounds to avoid CI flakiness on
    # transient indexer lag.
    expected_min_asset_counts = {
        "Database": 1,
        "Schema": 1,
        "Table": 2,
        "View": 1,
        "Column": 10,
    }
    # v_customer_order_totals drives view lineage parsing.
    expect_lineage = True

    def database_spec(self) -> DatabaseSpec:
        # ``host=mysql`` resolves over the compose default network to
        # the sibling mysql:8.0 the e2e-full overlay brings up.
        # Username/password match seed.sql's GRANT + the MYSQL_USER/
        # MYSQL_PASSWORD env on the mysql service.
        return DatabaseSpec(
            host="mysql",
            port=3306,
            username="e2e_user",
            password="e2e_pass",
            connector_config_name="atlan-connectors-mysql",
        )
