"""SDR (Self-Deployed Runtime) integration test for the MySQL app.

``atlan.yaml`` sets ``self_deployed_runtime: true``, so this app must have a
:class:`BaseSDRIntegrationTest` subclass to validate manifest inputs,
credential routing, and upload behaviour against a real SDR-like environment
(the atlan-configurator compose stack running on the CI runner).

``manifest_path`` points at the committed ``app/generated/manifest.json`` so
the workflow-scenario input is derived from the SAME ``dag.extract.inputs.args``
shape the platform submits in production — this is what would have caught the
missing ``agent_json`` slot in atlan-mssql-app#177.

TODO(human): ``scenarios`` is intentionally empty. Populate it with real
auth / preflight / workflow ``Scenario`` entries once the SDR compose stack
and ``E2E_MYSQL_*`` credential env vars are wired up in CI for this app (see
``BaseSDRIntegrationTest`` / ``Scenario`` docstrings in
``application_sdk.testing.sdr.base`` / ``application_sdk.testing.integration``
for the expected shape). An empty ``scenarios`` list means this class
contributes no collected tests today — it exists to hold the correct
``manifest_path``/``workflow_type`` wiring, not yet to exercise the SDR path.
"""

from __future__ import annotations

import pytest
from application_sdk.testing.sdr.base import BaseSDRIntegrationTest

pytestmark = pytest.mark.integration


class TestMySQLSDR(BaseSDRIntegrationTest):
    """SDR integration test for the MySQL connector's single entrypoint."""

    manifest_path = "app/generated/manifest.json"
    workflow_type = None

    scenarios = []
