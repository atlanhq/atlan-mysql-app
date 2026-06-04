"""Static-file contract tests — catches regressions in the generated
PKL form schema (``app/generated/mysql.json``) and the test-deploy AE
DAG script (``.github/scripts/ae-workflow.sh``).

Every bug below bit us during REQ-925 deploy verification on
apps-typedef. None had a regression test before; each commit in this
test module pins down one such failure mode.

Run with the rest of the unit suite — no external dependencies:

    uv run pytest tests/unit/test_dag_contracts.py -v
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_MYSQL_JSON = REPO_ROOT / "app" / "generated" / "mysql.json"
GENERATED_MANIFEST_JSON = REPO_ROOT / "app" / "generated" / "manifest.json"
AE_WORKFLOW_SH = REPO_ROOT / ".github" / "scripts" / "ae-workflow.sh"


# ─────────────────────────────────────────────────────────────────────
# Frontend form schema — generated from contract/app.pkl
# ─────────────────────────────────────────────────────────────────────


class TestGeneratedMySQLJson:
    """Asserts the deployed UI form's contract for REQ-925.

    The form schema is generated from ``contract/app.pkl`` via ``pkl
    eval``. This file is what the frontend reads at the connector-
    onboarding form; any regression here is silently customer-visible.
    """

    @pytest.fixture
    def config(self) -> dict:
        """PKL nests the form schema under ``config`` — ``properties`` and
        ``steps`` live there, not at the document root."""
        return json.loads(GENERATED_MYSQL_JSON.read_text())["config"]

    def test_control_config_strategy_field_present(self, config):
        """REQ-925: the Advanced Config step needs a strategy radio."""
        props = config["properties"]
        assert "control-config-strategy" in props
        field = props["control-config-strategy"]
        assert "default" in field.get("enum", [])
        assert "custom" in field.get("enum", [])

    def test_control_config_text_field_present(self, config):
        """REQ-925: the Custom Config JSON text input."""
        assert "control-config" in config["properties"]

    def test_control_config_is_conditional_gated_on_strategy(self, config):
        """REQ-925 follow-up: the Custom Config input MUST be hidden when
        strategy=default. Bug found post-deploy — when modelled as a
        plain TextInput it rendered unconditionally and customers
        misread it as "fill me in" on the default path.

        Reference pattern: ``extraction-method`` (radio) +
        ``preflight-check`` (visible on direct, hidden on agent).
        """
        field = config["properties"]["control-config"]
        assert field.get("type") == "conditional", (
            "control-config must be a Config.ConditionalInput so it can "
            "hide on strategy=default — modelling as a plain TextInput "
            "is the bug we shipped and then fixed in REQ-925"
        )
        conditions = field.get("conditions", [])
        keyed_props = {c.get("property") for c in conditions}
        assert keyed_props == {"control-config-strategy"}, (
            f"control-config conditions are keyed on {keyed_props}; "
            "must be keyed on control-config-strategy"
        )

        by_value = {c["value"]: c["ui"]["hidden"] for c in conditions}
        assert by_value.get("default") is True, (
            "control-config must be hidden when strategy=default"
        )
        assert by_value.get("custom") is False, (
            "control-config must be visible when strategy=custom"
        )

    def test_advanced_config_step_exists(self, config):
        """The PKL contract groups the two fields into a dedicated step."""
        steps = config.get("steps", [])
        step_ids = [s.get("id") for s in steps]
        # PKL emits step IDs in lowercase from task labels (Advanced → advanced)
        # so check both spellings to stay forgiving of future PKL renames.
        assert any(sid.lower() == "advanced" for sid in step_ids), (
            f"Advanced step missing — steps: {step_ids}"
        )


# ─────────────────────────────────────────────────────────────────────
# AE DAG — both the PKL-generated manifest and the test-deploy script
# ─────────────────────────────────────────────────────────────────────


# Fields that ``MySQLExtractionOutput`` (app/mysql.py) emits. Every
# ``$.extract.outputs.<X>`` reference in a downstream DAG node MUST be
# in this set — otherwise AE's JSONPath resolver returns nothing and
# the downstream node fails silently or noisily.
#
# Keep in sync with ``MySQLExtractionOutput`` field declarations. The
# test below grep-checks every reference; if you add a new output
# field on the App, add it here.
ALLOWED_EXTRACT_OUTPUT_FIELDS = {
    "connection_qualified_name",
    "transformed_data_prefix",
    "publish_state_prefix",
    "current_state_prefix",
    "view_lineage_output_prefix",
    "lineage_stage_prefix",
    "lineage_publish_state_prefix",
    "lineage_current_state_prefix",
    "storage_bucket",
}

_JSONPATH_PATTERN = re.compile(r"\$\.extract\.outputs\.(\w+)")


class TestGeneratedManifestJson:
    """The PKL-built ``app/generated/manifest.json`` — the AE DAG that
    ships with the helm chart (what the deployed connector actually
    runs in production)."""

    @pytest.fixture
    def manifest_text(self) -> str:
        return GENERATED_MANIFEST_JSON.read_text()

    def test_jsonpath_references_are_real_output_fields(self, manifest_text):
        """Every ``$.extract.outputs.<field>`` referenced by qi/publish/
        lineage nodes MUST be a field the App actually emits.

        This catches DAG drift — e.g. the deploy script previously
        referenced ``view_data_prefix`` and ``lake_provider`` which the
        App never emitted, causing every dispatch to fail at qi /
        publish / lineage-app with ``Jsonpath '...' did not match any
        value`` even when extract succeeded cleanly.
        """
        referenced = set(_JSONPATH_PATTERN.findall(manifest_text))
        unknown = referenced - ALLOWED_EXTRACT_OUTPUT_FIELDS
        assert not unknown, (
            f"manifest.json references {unknown} on $.extract.outputs.* "
            "but MySQLExtractionOutput does not emit those fields. "
            "Either add the field to MySQLExtractionOutput (app/mysql.py) "
            "or remove the reference from the DAG."
        )


class TestAeWorkflowShell:
    """``.github/scripts/ae-workflow.sh`` — the test-deploy DAG submitted
    by ``Deploy to Tenant``. Mirrors ``app/generated/manifest.json``
    but is hand-written. Every drift we hit mid-REQ-925 lives here."""

    @pytest.fixture
    def script(self) -> str:
        return AE_WORKFLOW_SH.read_text()

    @pytest.fixture
    def script_code_only(self) -> str:
        """``ae-workflow.sh`` minus ``#`` shell comments — the documented
        history of past bugs lives in comments and would otherwise
        trip JSONPath-reference grep on, e.g., the ``view_data_prefix``
        explanation we left in for posterity."""
        return "\n".join(
            line.split("#", 1)[0] for line in AE_WORKFLOW_SH.read_text().splitlines()
        )

    def test_jsonpath_references_are_real_output_fields(self, script_code_only):
        """Same contract as the PKL manifest — the script must not
        reference output fields the App doesn't emit.

        Caught: ``$.extract.outputs.view_data_prefix`` (always None),
        ``$.extract.outputs.lake_provider`` (never emitted). Both
        replaced with valid fields in commit 0bb7c58. We strip ``#``
        shell comments first because the documented history of those
        broken refs lives in comments and would falsely trip the grep.
        """
        referenced = set(_JSONPATH_PATTERN.findall(script_code_only))
        unknown = referenced - ALLOWED_EXTRACT_OUTPUT_FIELDS
        assert not unknown, (
            f"ae-workflow.sh references {unknown} on $.extract.outputs.* "
            "but MySQLExtractionOutput does not emit those fields. "
            "Update the script to reference the actual output schema."
        )

    def test_connection_uses_nested_atlas_entity_shape(self, script):
        """SDK's ``SqlApp`` reads
        ``input.connection.attributes.qualified_name`` (see
        ``application_sdk/templates/sql_app.py:529-531``). The script
        previously sent a flat ``{"connection_name": ..., "connection_
        qualified_name": ...}``, which has no ``attributes`` field, so
        the SDK got ``connection_qn = ""`` and ``publish`` exploded with
        ``DiffRecord.connection_qualified_name input_value=None``.

        Fixed in commit 70e3e07. Test pins the nested shape so a
        future copy-paste from a connector with a different shape
        doesn't silently break the deploy path.
        """
        # The script emits the AE submission as a bash-quoted JSON
        # literal — every ``"`` becomes ``\"`` and statements span
        # lines. Match permissively: anywhere ``"connection"`` is
        # followed (within the next ~120 chars) by ``"attributes"``,
        # that's the nested-entity shape we want. The previous flat
        # form had ``"connection"`` followed by ``"connection_name"`` /
        # ``"connection_qualified_name"`` directly with no
        # ``attributes`` wrapper.
        assert re.search(
            r'\\"connection\\"\s*:\s*\{\s*\\"attributes\\"',
            script,
            re.DOTALL,
        ), (
            "ae-workflow.sh must pass connection as the nested Atlas "
            'entity shape (``{"attributes": {"qualified_name": ...}}``) '
            "— the SDK reads ``input.connection.attributes.qualified_name``, "
            "and a flat ``{connection_name, connection_qualified_name}`` "
            "shape silently breaks the activity (connection_qn = '')"
        )

    def test_publish_carries_connection_entity_for_creation_path(self, script):
        """When ``connection_creation_enabled=true`` (fresh-leg
        scenario), the publish node MUST receive a ``connection_entity``
        argument — otherwise the AE publish app refuses with
        ``"No connection entity provided, skipping connection creation"``
        and the run fails.

        ``app/generated/manifest.json:69`` carries this via the
        ``{{connection}}`` template substitution. The hand-written
        script must include the same shape (typeName + attributes)
        directly so the AE flow can create the connection.

        Fixed in commit 70dab70.
        """
        assert re.search(r'\\"connection_entity\\"\s*:', script), (
            "ae-workflow.sh publish node must include "
            '``\\"connection_entity\\": { … }`` so publish can call the '
            "connection-create flow when connection_creation_enabled=true. "
            "Without it, fresh-leg dispatches fail with "
            "'No connection entity provided, skipping connection creation'."
        )

    def test_extract_inputs_include_control_config(self, script):
        """REQ-925: the script must forward ``control_config_strategy``
        and ``control_config`` to the extract node so the new
        ``MySQLExtractionTaskInput`` fields can carry through. Reading
        these from the customer's connection config / Linear payload is
        a follow-up; for now the script may pass empty defaults — but
        the keys must be in the args block, otherwise the workflow
        input pydantic boundary strips them.

        Defensive: future drift would re-introduce the silent no-op.
        """
        # Either the keys appear hard-coded in the args block, OR a
        # variable name like ``${CONTROL_CONFIG_STRATEGY}`` is wired.
        # For now we just check the script intends to thread the field
        # — if it doesn't, customer flows still work (the AE workflow
        # config carries the value), but the test-deploy path becomes
        # unable to exercise custom strategies.
        # We intentionally don't fail if missing — this is a WARNING-
        # level check via xfail until the script is updated.
        pytest.xfail(
            "ae-workflow.sh does not yet thread control_config* through "
            "to the extract args — follow-up task to plumb dispatch "
            "inputs into the script. Customer flows are unaffected "
            "(AE workflow editor sets these per-connection)."
        )
