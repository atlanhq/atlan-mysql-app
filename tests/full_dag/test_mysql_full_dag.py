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

    # Bring up the compose stack first (worker + sibling mysql + Dapr).
    # In CI this is the SDR composite action with e2e-full overrides;
    # locally you'd run:
    #   docker compose \\
    #     -f ci-deploy/docker-compose.yaml \\
    #     -f .github/actions/sdr-e2e/docker-compose.ci.yml \\
    #     -f .github/e2e/e2e-full-docker-compose.yaml \\
    #     up -d

    ATLAN_BASE_URL=https://<tenant-domain> \\
    ATLAN_API_KEY=... \\
    GITHUB_RUN_ID=$(date +%s) \\
    ATLAN_AUTH_CLIENT_ID=... ATLAN_AUTH_CLIENT_SECRET=... \\
        uv run pytest tests/full_dag/ -v

The test class skips gracefully when the harness env isn't configured,
so it can sit alongside the per-PR SDR integration suite without
breaking unrelated pytest invocations.
"""

from __future__ import annotations

import os

import pytest

# The full-DAG harness module is v3-SDK-only — `BaseFullDAGE2ETest`
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

from application_sdk.testing.full_dag import BaseFullDAGE2ETest, RunMode  # noqa: E402
from application_sdk.testing.full_dag.payload import (  # noqa: E402
    AgentSpec,
    ConnectionSpec,
    DatabaseSpec,
)
from pyatlan.client.atlan import AtlanClient  # noqa: E402


class TestMySQLFullDAG(BaseFullDAGE2ETest):
    """Submit an AE workflow targeting our CI-side worker + assert in Atlas.

    Class specifics:
        - ``mode = RunMode.AGENT`` — connector runs in CI compose, not
          in a tenant-deployed pod. AE dispatches to our unique queue.
        - ``app_service_url`` is metadata-only in agent mode (Temporal
          handles dispatch); we set it to the tenant's prod URL anyway
          for diagnostic clarity in the AE workflow's stored payload.
        - ``database_spec()`` points at the sibling ``mysql:8.0``
          brought up by the e2e-full compose overlay with the hermetic
          seed.sql dataset — three databases, ~20 rows total.
        - ``agent_spec()`` uses a unique agent-name keyed off ``run_id``
          so each CI run gets its own Temporal queue. The compose
          overlay sets ``ATLAN_DEPLOYMENT_NAME=e2e-full-ci-<run_id>``
          on the worker so it registers on that same queue.
    """

    connector_short_name = "mysql"
    argo_package_name = "@atlan/mysql"
    argo_template_name = "atlan-mysql"
    mode = RunMode.AGENT
    app_service_url = "http://mysql.mysql-app.svc.cluster.local"

    # Keep these scenario-config attrs at the class level rather than
    # in env so the test stays deterministic across reruns of the same
    # GitHub Actions workflow run.
    # Every name (Connection QN, AE workflow, queue, deployment) embeds
    # this prefix + run_id for cross-system traceability.
    connection_name_prefix = "e2e-full-ci"
    # MySQL's SQL templates expect a single anchored regex string
    # matching `<catalog>.<schema>` (NOT the v3 dict-shape JSON the
    # base harness defaults to — that substitutes into a literal
    # `REGEXP '{...}'` clause and the server rejects it with
    # pymysql 3688 / "Syntax error in regular expression"). The
    # connector's catalog is hardcoded to `def` for MySQL (see
    # extract_schema.sql); the schema is the actual database name.
    include_filter = r"^def\.e2e_main$"
    exclude_filter = ""
    # mysql's v3 extract bundles view definitions into the main
    # transformed output rather than a dedicated `view_data_prefix`
    # subfolder. Without this override AE fails the qi node with
    # `Jsonpath '$.extract.outputs.view_data_prefix' did not match any
    # value` and the lineage nodes get stuck Pending — blocking the
    # whole DAG and silently producing 0 published entities.
    qi_input_prefix_field = "transformed_data_prefix"
    # adminUsers / adminGroups intentionally left as the base-class
    # defaults (empty tuples). The Connection's admin ACL is set by
    # `connection_spec()` below, which resolves the tenant's `$admin`
    # role GUID via pyatlan's role_cache at run time. That role covers
    # both the API-key service account (without which the harness
    # probe gets ATLAS-403-00-001) and any tenant admin who wants to
    # inspect the run afterwards — no per-user hardcoding required.

    # Poll knobs.
    #   Interval: 60s for both AE + Atlas. We used to poll every 5/10s
    #     for tight terminal-state detection on the small seed, but
    #     the dominant cost is now the slow lineage stage (5-30 min);
    #     a 60s cadence is plenty granular and cuts API chatter by
    #     ~12x on long runs.
    #   Timeout: WIDE. lineage-app + lineage-publish can sit Running
    #     for tens of minutes on dev-tenant when the tenant's publish/
    #     lineage queues are deep or workers are cold-starting. Run
    #     25794699597 hit 12.5 min with lineage-app still Running.
    #     Budget the AE poll at 1.5 h so a busy tenant doesn't bury
    #     an otherwise-healthy run; Atlas search is cheap so 30 min
    #     there easily covers indexer lag.
    #     The GH job timeout (`timeout-minutes` in e2e-full.yaml) is
    #     bumped to 120 min in lockstep — must always be >
    #     ae_poll + atlas_poll + ~10 min build/setup overhead.
    ae_poll_interval_seconds = 60
    ae_poll_timeout_seconds = 5400
    atlas_poll_interval_seconds = 60
    atlas_poll_timeout_seconds = 1800

    # Expected Atlas inventory for the hermetic seed.sql restricted to
    # `e2e_main` (the include_filter above). Seed.sql under e2e_main
    # creates: one database, one schema (`def`), two tables (customers,
    # orders), one view (v_customer_order_totals), and 4+4+3=11 columns.
    # Floors only — Atlas can land more (e.g. system columns) without
    # breaking the assertion. Numbers chosen conservatively to avoid
    # CI flakiness on transient indexer lag for the trailing rows.
    expected_min_asset_counts = {
        "Database": 1,
        "Schema": 1,
        "Table": 2,
        "View": 1,
        "Column": 10,
    }
    # v_customer_order_totals reads from customers + orders, so view
    # lineage parsing in QI should emit at least one Process row.
    expect_lineage = True

    def connection_spec(self) -> ConnectionSpec:
        # Resolve the tenant's `$admin` role GUID via pyatlan's
        # role_cache so the API-key service account (which is in `$admin`
        # by default) ends up on the Connection's admin ACL — required
        # for the harness's back-side probe (without it, the GET returns
        # ATLAS-403-00-001). Cached on `self` so we don't pay the lookup
        # cost on every call inside the harness.
        if not hasattr(self, "_admin_role_guid"):
            client = AtlanClient(
                base_url=os.environ["ATLAN_BASE_URL"],
                api_key=os.environ["ATLAN_API_KEY"],
            )
            guid = client.role_cache.get_id_for_name("$admin")
            if guid is None:
                # role_cache returns None when the role doesn't exist on
                # this tenant. `$admin` is a built-in Atlan role so this
                # would only fire on a misconfigured tenant — fail loud
                # rather than silently dropping the back-side probe ACL.
                raise RuntimeError(
                    "pyatlan role_cache could not resolve `$admin` role GUID "
                    f"against {os.environ['ATLAN_BASE_URL']} — Connection "
                    "would land with empty adminRoles and the harness probe "
                    "would 403."
                )
            self._admin_role_guid = guid
        return ConnectionSpec(
            name=self.connection_display_name,
            qualified_name=self.connection_qualified_name,
            connector_name=self.connector_short_name,
            source_logo=f"https://assets.atlan.com/assets/{self.connector_short_name}.png",
            admin_users=self.connection_admin_users,
            admin_groups=self.connection_admin_groups,
            admin_roles=(self._admin_role_guid,),
        )

    def database_spec(self) -> DatabaseSpec:
        # `host=mysql` resolves over the compose default network to
        # the sibling mysql:8.0 the e2e-full overlay brings up. Username
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
        # agent_name carries the connector prefix because the Argo
        # cluster template routes task_queue = atlan-<agent_name>; the
        # prefix has to be on agent_name itself so worker (registered
        # on atlan-mysql-e2e-full-ci-<run_id>) and AE (dispatching to
        # atlan-{agent_name}) land on the same queue. Embedding
        # e2e-full-ci-<run_id> gives every test run a clearly-labeled
        # unique queue.
        return AgentSpec(agent_name=f"mysql-e2e-full-ci-{self.run_id}")
