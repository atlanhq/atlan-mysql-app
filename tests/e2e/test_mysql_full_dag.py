"""Full-DAG e2e test for the MySQL connector.

Runs against the tenant's full system-apps DAG (extract → qi → publish
→ lineage-app → lineage-publish). The connector code under test runs
in a CI-side docker compose worker (registered on a unique Temporal
queue named ``atlan-mysql-e2e-full-ci-<run_id>``); the AE workflow's
extract activity dispatches to that queue via ``agent-json.agent-name``
routing. Worker writes raw + transformed artifacts to the shared tenant
S3 bucket (via the object-store OAuth proxy in CI); the in-cluster
publish app reads from the same bucket.

To run locally::

    ATLAN_BASE_URL=<your-tenant-base-url> \
    ATLAN_API_KEY=... \
    GITHUB_RUN_ID=$(date +%s) \
        uv run pytest tests/e2e/ -v

The test class skips gracefully when the harness env isn't configured,
so it can sit alongside the per-PR integration suite without breaking
unrelated pytest invocations.
"""

from __future__ import annotations

import os

import pytest

if not os.environ.get("ATLAN_BASE_URL") or not os.environ.get("ATLAN_API_KEY"):
    pytest.skip(
        "Full-DAG e2e harness needs ATLAN_BASE_URL + ATLAN_API_KEY",
        allow_module_level=True,
    )

try:
    from application_sdk.testing.e2e import RunMode  # noqa: E402
    from application_sdk.testing.e2e.payload import DatabaseSpec, build_ae_payload  # noqa: E402
    from app.generated._e2e_base import MysqlGeneratedE2EBase  # noqa: E402
    from app.generated._e2e_credential import MysqlCredentialBody  # noqa: E402
except ImportError as _exc:
    pytest.skip(
        f"SDK does not yet export new e2e harness: {_exc}", allow_module_level=True
    )


class TestMySQLFullDAG(MysqlGeneratedE2EBase):
    """Submit an AE workflow targeting our CI-side worker + assert in Atlas.

    Inherits identity attrs, connection_spec (with $admin role ACL), and
    _mustache_substitutions from MysqlGeneratedE2EBase / SQLAppE2ETest.
    The base harness builds the connection QN as default/mysql/{epoch}
    automatically — no override needed.
    """

    mode = RunMode.AGENT

    # MySQL's SQL templates substitute include-filter into a literal
    # MySQL ``REGEXP '…'`` clause, so it expects an anchored regex
    # string (not the v3 dict-shape JSON the harness defaults to).
    include_filter = r"^def\.e2e_main$"
    exclude_filter = ""
    # mysql v3 bundles view definitions into the main transformed
    # output rather than a dedicated ``view_data_prefix`` subfolder.
    qi_input_prefix_field = "transformed_data_prefix"

    # Poll knobs sized for a real tenant — lineage-app + lineage-publish can
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

    def _credential_body(self) -> MysqlCredentialBody:
        # AGENT mode: lightweight body — no host/username/password.
        # Those live in the Dapr secret store and are resolved at runtime
        # via agent-json ref-keys. Sending the DIRECT-mode shape causes the
        # orchestrator to skip credential creation and leave {{credentialGuid}}
        # unsubstituted, which produces HTTP 500 at submit time.
        #
        # The GITHUB_RUN_ATTEMPT suffix guards against the Postgres
        # unique-constraint collision when the same run is re-attempted: run_id
        # is stable across attempts, so without the suffix a retry would POST a
        # credential name that already exists and fail with HTTP 400.
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        return MysqlCredentialBody(
            name=f"default-{self.connector_short_name}-{self.run_id}-{attempt}",
        )

    def _build_ae_payload(self, slug: str) -> dict:
        # The new build_ae_payload emits only the {{...}} mustache params and
        # connection.* attrs. The Argo cluster template additionally reads flat
        # credential-guid.* and agent-json.* params that the old harness sent.
        # Inject them here so the template sees the same shape it expects.
        payload = build_ae_payload(
            run_id=self.run_id,
            mode=self.mode,
            connector_short_name=self.connector_short_name,
            argo_package_name=self.argo_package_name,
            argo_template_name=self.argo_template_name,
            app_service_url=self.app_service_url,
            connection=self.connection_spec(),
            mustache_subs=self._mustache_substitutions(),
            credential_body=self._credential_body(),
            ae_workflow_slug=slug,
        )
        db = self.database_spec()
        agent = self.agent_spec()
        extra_params = [
            {
                "name": "credential-guid.credential-type",
                "value": db.connector_config_name
                or f"atlan-connectors-{self.connector_short_name}",
            },
            {"name": "credential-guid.port", "value": db.port},
            {"name": "credential-guid.auth-type", "value": db.auth_type},
        ]
        if agent is not None:
            extra_params.extend([
                {"name": "agent-json.host", "value": db.host},
                {"name": "agent-json.port", "value": db.port},
                {"name": "agent-json.auth-type", "value": db.auth_type},
                {"name": "agent-json.agent-name", "value": agent.agent_name},
                {"name": "agent-json.agent-type", "value": agent.agent_type},
                {"name": "agent-json.key-type", "value": agent.key_type},
                {"name": "agent-json.aws-auth-method", "value": agent.aws_auth_method},
                {
                    "name": "agent-json.azure-auth-method",
                    "value": agent.azure_auth_method,
                },
                {
                    "name": "agent-json.basic.username",
                    "value": f"SDR_{self.connector_short_name.upper()}_USERNAME",
                },
                {
                    "name": "agent-json.basic.password",
                    "value": f"SDR_{self.connector_short_name.upper()}_PASSWORD",
                },
            ])
        payload["spec"]["templates"][0]["dag"]["tasks"][0]["arguments"][
            "parameters"
        ].extend(extra_params)
        return payload
