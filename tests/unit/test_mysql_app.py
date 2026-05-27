"""Unit tests for MySQLApp (v3 SqlApp)."""

from __future__ import annotations

import pytest

from app.constants import DATABASE_PLACEHOLDER
from app.mysql import MySQLApp


class TestMySQLAppClassAttrs:
    """Verify class-level configuration."""

    def test_sql_client_class_set(self):
        from app.clients import SQLClient

        assert MySQLApp.sql_client_class is SQLClient

    def test_fetch_database_sql_loaded(self):
        assert MySQLApp.fetch_database_sql != ""
        assert DATABASE_PLACEHOLDER in MySQLApp.fetch_database_sql
        assert "{database_placeholder}" not in MySQLApp.fetch_database_sql

    def test_fetch_schema_sql_loaded(self):
        assert MySQLApp.fetch_schema_sql != ""

    def test_fetch_table_sql_loaded(self):
        assert MySQLApp.fetch_table_sql != ""

    def test_fetch_column_sql_loaded(self):
        assert MySQLApp.fetch_column_sql != ""

    def test_fetch_procedure_sql_loaded(self):
        assert MySQLApp.fetch_procedure_sql != ""

    def test_temp_table_regex_fragments_loaded(self):
        assert MySQLApp.extract_temp_table_regex_table_sql != ""
        assert MySQLApp.extract_temp_table_regex_column_sql != ""

    def test_database_placeholder_substituted_in_all_sql(self):
        """All SQL attrs should have {database_placeholder} replaced."""
        for attr in [
            "fetch_database_sql",
            "fetch_schema_sql",
            "fetch_table_sql",
            "fetch_column_sql",
            "fetch_procedure_sql",
        ]:
            sql = getattr(MySQLApp, attr)
            assert "{database_placeholder}" not in sql, f"{attr} still has placeholder"

    def test_information_schema_placeholder_present_in_ddl_sql(self):
        """`{information_schema}` must be present in the SQL ClassVars so runtime
        resolution (_prepare_sql) can swap it for either the canonical schema
        or a customer-provided mirror schema (REQ-925)."""
        for attr in [
            "fetch_database_sql",
            "fetch_schema_sql",
            "fetch_table_sql",
            "fetch_column_sql",
            "fetch_procedure_sql",
        ]:
            sql = getattr(MySQLApp, attr)
            assert "{information_schema}" in sql, (
                f"{attr} lost the {{information_schema}} placeholder — "
                "runtime resolution would silently fail"
            )

    def test_excluded_schemas_placeholder_present_in_ddl_sql(self):
        """`{excluded_schemas}` must be in every SQL ClassVar so _prepare_sql
        can render either the default 4-schema list or the 5-schema list that
        includes the customer's mirror. Without it, the mirror's pass-through
        views would be crawled as user assets."""
        for attr in [
            "fetch_database_sql",
            "fetch_schema_sql",
            "fetch_table_sql",
            "fetch_column_sql",
            "fetch_procedure_sql",
        ]:
            sql = getattr(MySQLApp, attr)
            assert "{excluded_schemas}" in sql, (
                f"{attr} lost the {{excluded_schemas}} placeholder — "
                "the mirror schema would leak into the crawl"
            )
            # And the OLD literal must be gone — if any file still hardcodes
            # the list, the mirror auto-exclusion silently breaks for it.
            assert (
                "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')"
                not in sql
            ), (
                f"{attr} still contains the hardcoded exclusion list — "
                "every site must go through {excluded_schemas}"
            )

    def test_prepare_sql_resolves_default_information_schema(self):
        """Without control-config, _prepare_sql substitutes the canonical schema.

        Backward-compat check: output SQL must be byte-equivalent to today
        (matches what currently ships from main when no override is set).
        ``_prepare_sql`` reads control-config from the ``input`` arg — the
        task input must therefore carry the (empty) defaults.
        """
        from unittest.mock import MagicMock

        app = MySQLApp()
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = "default"
        input_.control_config = ""

        prepared = app._prepare_sql(MySQLApp.fetch_table_sql, input_)
        assert "{information_schema}" not in prepared
        assert "information_schema.TABLES" in prepared

    def test_prepare_sql_resolves_mirror_information_schema(self):
        """Control-config on the task input → ``_prepare_sql`` rewrites.

        Mirrors the on-the-wire shape: ``MySQLExtractionTaskInput`` arrives
        at the activity with the typed fields populated by
        ``MySQLApp.build_task_input``. ``_prepare_sql`` reads via
        ``extract_control_config(input)`` and rewrites every
        ``{information_schema}`` placeholder to the mirror name.
        """
        from unittest.mock import MagicMock

        app = MySQLApp()
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = "custom"
        input_.control_config = {"clonedInformationSchema": "atlan_meta"}

        prepared = app._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        assert "{information_schema}" not in prepared
        assert "atlan_meta.SCHEMATA" in prepared
        assert "atlan_meta.TABLES" in prepared
        # The literal "information_schema" inside the NOT IN clause is untouched
        # — that's a system-schema name to filter out, not a query target.
        assert "'information_schema'" in prepared

    def test_prepare_sql_renders_default_excluded_schemas(self):
        """Without control-config, _prepare_sql renders the original 4-schema list.

        Backward-compat check: the rendered NOT IN list must equal the literal
        that lived in every SQL file pre-fix.
        """
        from unittest.mock import MagicMock

        app = MySQLApp()
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = "default"
        input_.control_config = ""

        prepared = app._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        assert "{excluded_schemas}" not in prepared
        assert (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')"
            in prepared
        )
        # Mirror name must NOT appear when no override was supplied.
        assert "'atlan_meta'" not in prepared

    def test_prepare_sql_appends_mirror_to_excluded_schemas(self):
        """When clonedInformationSchema is set, _prepare_sql appends the mirror
        name to the NOT IN list — so the mirror's pass-through views are not
        crawled as user assets (REQ-925)."""
        from unittest.mock import MagicMock

        app = MySQLApp()
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = "custom"
        input_.control_config = {"clonedInformationSchema": "atlan_meta"}

        for attr in [
            "fetch_database_sql",
            "fetch_schema_sql",
            "fetch_table_sql",
            "fetch_column_sql",
            "fetch_procedure_sql",
        ]:
            prepared = app._prepare_sql(getattr(MySQLApp, attr), input_)
            assert (
                "{excluded_schemas}" not in prepared
            ), f"{attr}: {{excluded_schemas}} placeholder not resolved"
            assert (
                "NOT IN ('mysql', 'performance_schema', 'information_schema', "
                "'sys', 'atlan_meta')"
            ) in prepared, f"{attr}: mirror schema name not appended to exclusion list"

    def test_run_parses_control_config_from_pydantic_input(self):
        """REQ-925 regression: pydantic-v2 default ``extra='ignore'`` was
        silently dropping ``control_config_strategy`` / ``control_config``
        at the ``ExtractionInput`` boundary, so ``_prepare_sql`` always saw
        empty control-config and queried native ``information_schema``.

        Verifies the fix end-to-end: build a ``MySQLExtractionInput`` from
        a raw dict (the AE payload shape) and confirm the typed fields
        survive validation and ``extract_control_config`` reads them.
        """
        from app.mysql import MySQLExtractionInput
        from app.utils import extract_control_config

        # AE payload shape (what arrives over the wire).
        payload = {
            "workflow_id": "wf-123",
            "credential_guid": "cred-456",
            "extraction_method": "direct",
            "control_config_strategy": "custom",
            "control_config": {"clonedInformationSchema": "atlan_meta"},
        }
        model = MySQLExtractionInput.model_validate(payload)
        # Typed fields must survive — pre-fix they were dropped.
        assert model.control_config_strategy == "custom"
        assert model.control_config == {"clonedInformationSchema": "atlan_meta"}
        # ``extract_control_config`` must return the parsed dict.
        assert extract_control_config(model) == {
            "clonedInformationSchema": "atlan_meta",
        }

    def test_build_task_input_threads_control_config_to_task(self):
        """REQ-925 regression: control-config must travel ON the task input
        across the workflow→activity worker boundary.

        Each ``@task`` activity runs on a FRESH ``app_instance = app_cls()``
        (``application_sdk/app/base.py:1478``); the workflow-side
        ``self._control_config`` is invisible to the activity. The ONLY
        contract Temporal preserves is the typed input object.

        ``MySQLApp.build_task_input`` overrides the SDK staticmethod to
        upgrade ``ExtractionTaskInput`` → ``MySQLExtractionTaskInput`` and
        copy ``control_config_strategy`` + ``control_config`` from the
        workflow input. This test asserts that contract end-to-end.
        """
        from application_sdk.templates.contracts.sql_metadata import (
            ExtractionTaskInput as _SDKExtractionTaskInput,
        )

        from app.mysql import MySQLApp, MySQLExtractionInput, MySQLExtractionTaskInput

        src = MySQLExtractionInput.model_validate({
            "workflow_id": "wf-123",
            "credential_guid": "cred-456",
            "extraction_method": "direct",
            "control_config_strategy": "custom",
            "control_config": {"clonedInformationSchema": "atlan_meta"},
        })
        task_input = MySQLApp.build_task_input(_SDKExtractionTaskInput, src)

        # The SDK requested ``ExtractionTaskInput`` but the override
        # upgraded to the MySQL subclass so the control-config fields
        # survive the activity boundary.
        assert isinstance(task_input, MySQLExtractionTaskInput)
        assert task_input.control_config_strategy == "custom"
        assert task_input.control_config == {"clonedInformationSchema": "atlan_meta"}

    def test_extract_task_signatures_use_mysql_subclass(self):
        """REQ-925 regression: the @task method annotations must declare
        ``MySQLExtractionTaskInput`` (not the SDK base) so pydantic
        deserialisation on the activity side preserves the typed
        control-config fields. The SDK base ``ExtractionTaskInput`` has
        ``model_config = ConfigDict()`` (extra='ignore') and would strip
        them at the activity-side reconstruction.
        """
        from typing import get_type_hints

        from app.mysql import MySQLApp, MySQLExtractionTaskInput

        for method_name in (
            "extract_databases",
            "extract_schemas",
            "extract_tables",
            "extract_columns",
            "extract_procedures",
        ):
            method = getattr(MySQLApp, method_name)
            # ``from __future__ import annotations`` makes raw signatures
            # string-typed. ``get_type_hints`` resolves them to real classes
            # against the method's module globals — needed to compare
            # identity rather than name.
            hints = get_type_hints(method)
            assert hints.get("input") is MySQLExtractionTaskInput, (
                f"{method_name} annotation is {hints.get('input')!r}; "
                "must be MySQLExtractionTaskInput so the activity-side "
                "pydantic round-trip preserves control_config fields"
            )


class TestMySQLAppMappers:
    """Test asset mapper functions."""

    @pytest.fixture
    def app(self):
        return MySQLApp()

    @pytest.fixture
    def connection_qn(self):
        return "default/mysql/1234567890"

    def test_map_database(self, app, connection_qn):
        record = {"database_name": "def", "schema_count": 5}
        result = app.map_database(record, connection_qn)
        assert result["typeName"] == "Database"
        assert result["attributes"]["name"] == "def"
        assert result["attributes"]["qualifiedName"] == f"{connection_qn}/def"
        assert result["attributes"]["connectorName"] == "mysql"
        assert result["attributes"]["schemaCount"] == 5
        assert result["tenantId"] == "default"
        assert "customAttributes" in result

    def test_map_schema(self, app, connection_qn):
        record = {
            "catalog_name": "def",
            "schema_name": "mydb",
            "table_count": 10,
            "views_count": 3,
        }
        result = app.map_schema(record, connection_qn)
        assert result["typeName"] == "Schema"
        assert result["attributes"]["name"] == "mydb"
        assert result["attributes"]["qualifiedName"] == f"{connection_qn}/def/mydb"
        assert result["attributes"]["databaseName"] == "def"
        assert result["attributes"]["tableCount"] == 10
        assert result["attributes"]["viewsCount"] == 3
        assert result["attributes"]["database"]["typeName"] == "Database"

    def test_map_table_base_table(self, app, connection_qn):
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "users",
            "table_kind": "BASE TABLE",
            "column_count": 5,
            "row_count": 100,
        }
        result = app.map_table(record, connection_qn)
        assert result["typeName"] == "Table"
        assert result["attributes"]["name"] == "users"
        assert (
            result["attributes"]["qualifiedName"] == f"{connection_qn}/def/mydb/users"
        )
        assert result["attributes"]["columnCount"] == 5
        assert result["attributes"]["rowCount"] == 100
        assert result["attributes"]["subType"] == "TABLE"
        assert result["attributes"]["atlanSchema"]["typeName"] == "Schema"

    def test_map_table_view(self, app, connection_qn):
        """Views are returned as typeName=View based on table_kind."""
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "active_users_view",
            "table_kind": "VIEW",
            "view_definition": "SELECT * FROM users WHERE active=1",
        }
        result = app.map_table(record, connection_qn)
        assert result["typeName"] == "View"
        assert result["attributes"]["name"] == "active_users_view"
        assert result["attributes"]["definition"] == (
            "CREATE OR REPLACE VIEW active_users_view AS SELECT * FROM users WHERE active=1"
        )
        assert result["attributes"]["description"] == "VIEW"
        assert "rowCount" not in result["attributes"]
        # QI reads defaultCatalogName/defaultSchemaName from top-level entity fields
        # to write them to success.json rows for lineage-app catalog resolution.
        assert result["defaultCatalogName"] == "def"
        assert result["defaultSchemaName"] == "mydb"

    def test_map_table_table_has_no_default_catalog_fields(self, app, connection_qn):
        """Tables must NOT have defaultCatalogName — only views need it for QI."""
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "users",
            "table_kind": "BASE TABLE",
        }
        result = app.map_table(record, connection_qn)
        assert "defaultCatalogName" not in result
        assert "defaultSchemaName" not in result

    def test_map_table_system_view(self, app, connection_qn):
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "sys_view",
            "table_kind": "SYSTEM VIEW",
        }
        result = app.map_table(record, connection_qn)
        assert result["typeName"] == "View"

    def test_map_column(self, app, connection_qn):
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "users",
            "column_name": "email",
            "table_type": "BASE TABLE",
            "data_type": "varchar",
            "max_length": 255,
            "is_nullable": "YES",
            "ordinal_position": 3,
            "column_default": None,
            "constraint_type": "",
        }
        result = app.map_column(record, connection_qn)
        assert result["typeName"] == "Column"
        assert result["attributes"]["name"] == "email"
        assert (
            result["attributes"]["qualifiedName"]
            == f"{connection_qn}/def/mydb/users/email"
        )
        assert result["attributes"]["dataType"] == "VARCHAR"
        assert result["attributes"]["maxLength"] == 255
        assert result["attributes"]["isNullable"] is True
        assert result["attributes"]["order"] == 3
        assert result["attributes"]["table"]["typeName"] == "Table"
        assert "customAttributes" in result

    def test_map_column_not_nullable(self, app, connection_qn):
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "users",
            "column_name": "id",
            "table_type": "BASE TABLE",
            "is_nullable": "NO",
        }
        result = app.map_column(record, connection_qn)
        assert result["attributes"]["isNullable"] is False

    def test_map_column_view(self, app, connection_qn):
        """View columns have view ref instead of table ref."""
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "active_view",
            "column_name": "name",
            "table_type": "VIEW",
        }
        result = app.map_column(record, connection_qn)
        assert "view" in result["attributes"]
        assert result["attributes"]["view"]["typeName"] == "View"
        assert "table" not in result["attributes"]
        assert result["attributes"]["viewName"] == "active_view"


class TestMySQLAppHierarchy:
    """Test class hierarchy."""

    def test_extends_sql_app(self):
        from application_sdk.templates.sql_app import SqlApp

        assert issubclass(MySQLApp, SqlApp)

    def test_app_name(self):
        assert MySQLApp.name == "mysql"
        assert MySQLApp._app_name == "mysql"


class TestMapProcedure:
    """Tests for MySQLApp.map_procedure()."""

    @pytest.fixture
    def app(self):
        return MySQLApp.__new__(MySQLApp)

    @pytest.fixture
    def connection_qn(self):
        return "default/mysql/123"

    @pytest.fixture
    def basic_record(self):
        return {
            "procedure_catalog": "def",
            "procedure_schema": "atlan",
            "procedure_name": "count_rows",
            "procedure_definition": "BEGIN SELECT COUNT(*) FROM bigtable; END",
            "procedure_type": "PROCEDURE",
        }

    def test_type_name_is_procedure(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["typeName"] == "Procedure"

    def test_status_active(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["status"] == "ACTIVE"

    def test_qualified_name_format(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        # Must match legacy format: connection/db/schema/_procedures_/name
        assert result["attributes"]["qualifiedName"] == (
            "default/mysql/123/def/atlan/_procedures_/count_rows"
        )

    def test_definition_stored(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["attributes"]["definition"] == (
            "BEGIN SELECT COUNT(*) FROM bigtable; END"
        )

    def test_sub_type(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["attributes"]["subType"] == "PROCEDURE"

    def test_schema_ref(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        attrs = result["attributes"]
        assert attrs["atlanSchema"]["typeName"] == "Schema"
        assert attrs["atlanSchema"]["uniqueAttributes"]["qualifiedName"] == (
            "default/mysql/123/def/atlan"
        )

    def test_connector_name(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["attributes"]["connectorName"] == "mysql"

    def test_tenant_id(self, app, basic_record, connection_qn):
        from app.constants import TENANT_ID

        result = app.map_procedure(basic_record, connection_qn)
        assert result["tenantId"] == TENANT_ID
        assert result["attributes"]["tenantId"] == TENANT_ID

    def test_hierarchy_qualified_names(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        attrs = result["attributes"]
        assert attrs["databaseQualifiedName"] == "default/mysql/123/def"
        assert attrs["schemaQualifiedName"] == "default/mysql/123/def/atlan"
        assert attrs["databaseName"] == "def"
        assert attrs["schemaName"] == "atlan"

    def test_source_timestamps_set_when_present(self, app, connection_qn):
        record = {
            "procedure_catalog": "def",
            "procedure_schema": "atlan",
            "procedure_name": "proc",
            "procedure_definition": "BEGIN END",
            "procedure_type": "PROCEDURE",
            "created": "2026-01-01 12:00:00",
            "last_altered": "2026-02-01 12:00:00",
        }
        result = app.map_procedure(record, connection_qn)
        assert "sourceCreatedAt" in result["attributes"]
        assert "sourceUpdatedAt" in result["attributes"]

    def test_source_timestamps_absent_when_missing(
        self, app, basic_record, connection_qn
    ):
        result = app.map_procedure(basic_record, connection_qn)
        assert "sourceCreatedAt" not in result["attributes"]
        assert "sourceUpdatedAt" not in result["attributes"]

    def test_empty_definition_defaults_to_empty_string(self, app, connection_qn):
        record = {
            "procedure_catalog": "def",
            "procedure_schema": "atlan",
            "procedure_name": "proc",
            "procedure_definition": None,
            "procedure_type": "FUNCTION",
        }
        result = app.map_procedure(record, connection_qn)
        assert result["attributes"]["definition"] == ""
        assert result["attributes"]["subType"] == "FUNCTION"

    def test_missing_catalog_uses_placeholder(self, app, connection_qn):
        from app.constants import DATABASE_PLACEHOLDER

        record = {
            "procedure_schema": "atlan",
            "procedure_name": "proc",
            "procedure_definition": "BEGIN END",
        }
        result = app.map_procedure(record, connection_qn)
        assert result["attributes"]["databaseName"] == DATABASE_PLACEHOLDER


class TestMySQLExtractionOutput:
    """Tests for MySQLExtractionOutput dataclass."""

    def test_default_fields_empty(self):
        from app.mysql import MySQLExtractionOutput

        out = MySQLExtractionOutput()
        assert out.connection_qualified_name == ""
        assert out.transformed_data_prefix == ""
        assert out.view_lineage_output_prefix == ""
        assert out.lineage_stage_prefix == ""
        assert out.lineage_publish_state_prefix == ""
        assert out.lineage_current_state_prefix == ""
        assert out.storage_bucket == ""

    def test_fields_populated(self):
        from app.mysql import MySQLExtractionOutput

        out = MySQLExtractionOutput(
            connection_qualified_name="default/mysql/123",
            transformed_data_prefix="artifacts/apps/mysql/workflows/wf/transformed",
            view_lineage_output_prefix="artifacts/apps/mysql/workflows/wf/view_lineage",
            lineage_stage_prefix="artifacts/apps/mysql/workflows/wf/lineage_stage",
            storage_bucket="my-bucket",
        )
        assert out.connection_qualified_name == "default/mysql/123"
        assert out.view_lineage_output_prefix.endswith("view_lineage")
        assert out.lineage_stage_prefix.endswith("lineage_stage")
        assert out.storage_bucket == "my-bucket"

    def test_fetch_procedure_sql_loaded(self):
        """Procedure SQL template is loaded at class level."""
        assert MySQLApp.fetch_procedure_sql != ""
        assert "ROUTINE_DEFINITION" in MySQLApp.fetch_procedure_sql
        assert "ROUTINE_SCHEMA" in MySQLApp.fetch_procedure_sql


class TestMaterializeMirrorIntoInput:
    """REQ-925 follow-up: ``_materialize_mirror_into_input(creds, input)``
    is a synchronous helper called from ``_init_sql_client`` (activity
    context). It reads ``extra.clonedInformationSchema`` from a resolved
    credentials dict and writes it into ``input.control_config`` so the
    upcoming ``_prepare_sql`` call(s) on the same activity see the
    mirror schema.

    The helper itself doesn't resolve credentials — that's done by its
    caller. Tests here drive it directly with synthetic creds dicts of
    each shape we want to handle.
    """

    def _make_app(self):
        return MySQLApp.__new__(MySQLApp)

    def _input(self, **kwargs):
        from app.mysql import MySQLExtractionInput

        defaults = {
            "workflow_id": "wf-test",
            "credential_guid": "cred-test",
            "extraction_method": "direct",
        }
        defaults.update(kwargs)
        return MySQLExtractionInput.model_validate(defaults)

    def test_no_mirror_in_credential_no_mutation(self):
        """When the credentials dict has no ``clonedInformationSchema`` in
        any shape, the input is left untouched and extracts default to
        native ``information_schema``."""
        app = self._make_app()
        input_ = self._input()
        before_strategy = input_.control_config_strategy
        before_config = input_.control_config

        app._materialize_mirror_into_input({"host": "x", "port": "3306"}, input_)

        assert input_.control_config_strategy == before_strategy
        assert input_.control_config == before_config

    def test_nested_extra_dict_shape(self):
        """``creds["extra"]["clonedInformationSchema"]`` — handler-style nested."""
        app = self._make_app()
        input_ = self._input()
        app._materialize_mirror_into_input(
            {"extra": {"clonedInformationSchema": "atlan_meta"}}, input_
        )
        assert input_.control_config_strategy == "custom"
        assert input_.control_config == {"clonedInformationSchema": "atlan_meta"}

    def test_flat_dotted_key_shape(self):
        """``creds["extra.clonedInformationSchema"]`` — flat dotted-key fallback."""
        app = self._make_app()
        input_ = self._input()
        app._materialize_mirror_into_input(
            {"extra.clonedInformationSchema": "atlan_meta"}, input_
        )
        assert input_.control_config == {"clonedInformationSchema": "atlan_meta"}

    def test_top_level_fallback_shape(self):
        """``creds["clonedInformationSchema"]`` — top-level last-resort fallback."""
        app = self._make_app()
        input_ = self._input()
        app._materialize_mirror_into_input(
            {"clonedInformationSchema": "atlan_meta"}, input_
        )
        assert input_.control_config == {"clonedInformationSchema": "atlan_meta"}

    def test_existing_control_config_wins(self):
        """If the operator already set ``clonedInformationSchema`` via legacy
        Advanced Config JSON, that explicit override wins."""
        app = self._make_app()
        input_ = self._input(
            control_config_strategy="custom",
            control_config={"clonedInformationSchema": "operator_choice"},
        )
        app._materialize_mirror_into_input(
            {"extra": {"clonedInformationSchema": "credential_choice"}}, input_
        )
        assert input_.control_config == {"clonedInformationSchema": "operator_choice"}

    def test_whitespace_only_value_ignored(self):
        """A whitespace-only mirror value must not produce an empty string
        that downstream SQL identifier validation would reject."""
        app = self._make_app()
        input_ = self._input()
        app._materialize_mirror_into_input(
            {"extra": {"clonedInformationSchema": "   "}}, input_
        )
        assert input_.control_config_strategy == "default"

    def test_non_dict_creds_safe(self):
        """Defensive: a non-dict creds value (e.g. ``None`` if resolver
        returned nothing) doesn't crash; the helper just does nothing."""
        app = self._make_app()
        input_ = self._input()
        app._materialize_mirror_into_input(None, input_)  # type: ignore[arg-type]
        app._materialize_mirror_into_input({}, input_)
        assert input_.control_config_strategy == "default"


class TestInitSqlClientMaterializesMirror:
    """REQ-925 follow-up: ``_init_sql_client`` (activity-context override)
    resolves the credential via the SDK's secret store, then calls
    ``_materialize_mirror_into_input`` to inject the mirror schema into
    ``input.control_config`` before any extract SQL runs.
    """

    def _make_app(self):
        return MySQLApp.__new__(MySQLApp)

    def _input(self, **kwargs):
        from app.mysql import MySQLExtractionInput

        defaults = {
            "workflow_id": "wf-test",
            "credential_guid": "cred-test",
            "extraction_method": "direct",
        }
        defaults.update(kwargs)
        return MySQLExtractionInput.model_validate(defaults)

    def _patch_resolver(self, fake_creds):
        """Stub the secret store + resolver to return ``fake_creds``."""
        from contextlib import ExitStack
        from unittest.mock import AsyncMock, MagicMock, patch

        stack = ExitStack()
        fake_secret_store = MagicMock()
        fake_infra = MagicMock(secret_store=fake_secret_store)
        stack.enter_context(
            patch("app.mysql.get_infrastructure", return_value=fake_infra)
        )
        fake_resolver = MagicMock()
        fake_resolver.resolve_raw = AsyncMock(return_value=fake_creds)
        stack.enter_context(
            patch("app.mysql.CredentialResolver", return_value=fake_resolver)
        )
        return stack

    def test_init_sql_client_injects_mirror_from_extras(self):
        """End-to-end on the activity path: resolved creds carry the mirror;
        ``_init_sql_client`` writes it into ``input.control_config``."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        app = self._make_app()
        # Stub the sql_client_class so we don't try to make a real connection
        fake_client = MagicMock()
        fake_client.load = AsyncMock()
        with patch.object(MySQLApp, "sql_client_class", return_value=fake_client):
            input_ = self._input()
            with self._patch_resolver(
                fake_creds={
                    "host": "x",
                    "extra": {"clonedInformationSchema": "atlan_meta"},
                }
            ):
                asyncio.get_event_loop().run_until_complete(
                    app._init_sql_client(input_)
                )

        assert input_.control_config_strategy == "custom"
        assert input_.control_config == {"clonedInformationSchema": "atlan_meta"}
        # client.load was called with the raw creds dict (unmodified)
        fake_client.load.assert_awaited_once()

    def test_init_sql_client_no_mirror_no_mutation(self):
        """When the resolved credential has no mirror, the activity proceeds
        normally and the input control_config stays at its default."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        app = self._make_app()
        fake_client = MagicMock()
        fake_client.load = AsyncMock()
        with patch.object(MySQLApp, "sql_client_class", return_value=fake_client):
            input_ = self._input()
            with self._patch_resolver(fake_creds={"host": "x", "port": "3306"}):
                asyncio.get_event_loop().run_until_complete(
                    app._init_sql_client(input_)
                )

        assert input_.control_config_strategy == "default"


class TestMySQLAppRun:
    """Tests for MySQLApp.run() — verifies workflow.info() is used for output
    prefix derivation, not build_output_path() which crashes in workflow context.

    These guard against regressions where build_output_path() (activity-only)
    accidentally replaces the workflow.info() calls.
    """

    def _make_app(self):
        app = MySQLApp.__new__(MySQLApp)
        app._app_name = "mysql"
        return app

    def _mock_workflow_info(self, wf_id="wf-test-123", run_id="run-test-456"):
        from unittest.mock import MagicMock

        info = MagicMock()
        info.workflow_id = wf_id
        info.run_id = run_id
        return info

    def _run(self, app, input_, wf_info):
        """Run MySQLApp.run() with all SQL tasks mocked out."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from application_sdk.templates.contracts.sql_metadata import (
            ExtractionTaskOutput,
        )

        # SDK v3.12+ (BLDX-1281): each extract_* returns
        # ``ExtractionTaskOutput`` with a ``raw_file: FileReference | None``
        # field. ``run()`` reads ``.raw_file`` and threads it into the
        # matching transform via ``_build_transform_input``, which
        # Pydantic-validates the ref against ``FileReference`` —
        # MagicMock auto-attrs would fail that validation. Use real
        # ``ExtractionTaskOutput`` instances with ``raw_file=None``.
        def _extract_result(entity: str, count: int) -> ExtractionTaskOutput:
            return ExtractionTaskOutput(
                typename=entity, total_record_count=count, raw_file=None
            )

        with (
            patch("temporalio.workflow.info", return_value=wf_info),
            patch.object(
                MySQLApp,
                "extract_databases",
                new=AsyncMock(return_value=_extract_result("database", 1)),
            ),
            patch.object(
                MySQLApp,
                "extract_schemas",
                new=AsyncMock(return_value=_extract_result("schema", 1)),
            ),
            patch.object(
                MySQLApp,
                "extract_tables",
                new=AsyncMock(return_value=_extract_result("table", 2)),
            ),
            patch.object(
                MySQLApp,
                "extract_columns",
                new=AsyncMock(return_value=_extract_result("column", 5)),
            ),
            patch.object(
                MySQLApp,
                "extract_procedures",
                new=AsyncMock(return_value=_extract_result("procedure", 1)),
            ),
            patch.object(
                MySQLApp, "transform_databases", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(
                MySQLApp, "transform_schemas", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(
                MySQLApp, "transform_tables", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(
                MySQLApp, "transform_columns", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(
                MySQLApp,
                "transform_procedures",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch.object(MySQLApp, "_resolve_credential_ref", return_value=None),
            # SDK v3.13.2 added a prime_sql_auth call at the start of
            # SqlApp.run() that actually loads credentials. The unit tests
            # exercise run() with empty credentials (we're only validating
            # workflow-prefix / lineage-output wiring, not real auth), so
            # stub it to a no-op. Real auth is covered by integration tests.
            patch.object(
                MySQLApp, "prime_sql_auth", new=AsyncMock(return_value=MagicMock())
            ),
        ):
            return asyncio.get_event_loop().run_until_complete(app.run(input_))

    def test_lineage_prefixes_use_workflow_id_and_run_id(self):
        """view_lineage_output_prefix and lineage_stage_prefix must contain the
        workflow_id and run_id from workflow.info() — not activity context values."""
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info("my-wf-id", "my-run-id")
        result = self._run(app, ExtractionInput(output_path=""), info)

        assert "my-wf-id" in result.view_lineage_output_prefix
        assert "my-run-id" in result.view_lineage_output_prefix
        assert "my-wf-id" in result.lineage_stage_prefix
        assert "my-run-id" in result.lineage_stage_prefix

    def test_lineage_prefixes_end_with_correct_suffixes(self):
        """Each lineage prefix must end with its semantic directory name."""
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        result = self._run(app, ExtractionInput(output_path=""), info)

        assert result.view_lineage_output_prefix.endswith(
            "view_lineage"
        ) or result.view_lineage_output_prefix.endswith("view_lineage/")
        assert result.lineage_stage_prefix.endswith(
            "lineage_stage"
        ) or result.lineage_stage_prefix.endswith("lineage_stage/")
        assert result.lineage_publish_state_prefix.endswith(
            "lineage_publish_state"
        ) or result.lineage_publish_state_prefix.endswith("lineage_publish_state/")
        assert result.lineage_current_state_prefix.endswith(
            "lineage_current_state"
        ) or result.lineage_current_state_prefix.endswith("lineage_current_state/")

    def test_explicit_output_path_used_directly(self):
        """When input.output_path is set, it is used as base without calling workflow.info()."""
        from unittest.mock import patch

        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        with patch("temporalio.workflow.info", return_value=info):
            result = self._run(
                app,
                ExtractionInput(
                    output_path="./local/tmp/artifacts/apps/mysql/workflows/explicit-wf/run-1"
                ),
                info,
            )
        # With explicit output_path, lineage prefixes derive from it
        assert "explicit-wf" in result.view_lineage_output_prefix

    def test_build_output_path_never_called(self):
        """build_output_path() (activity-only) is NOT in mysql.py imports — verifies
        it was removed and won't accidentally be re-introduced causing a crash."""
        import app.mysql as mysql_module

        assert not hasattr(mysql_module, "build_output_path"), (
            "build_output_path is imported in mysql.py — it will crash in workflow "
            "context with 'Not in activity context'. Use workflow.info() instead."
        )

    def test_storage_bucket_from_env(self):
        """storage_bucket is read from S3_BUCKET env var."""
        import os
        from unittest.mock import patch

        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()

        with patch.dict(os.environ, {"S3_BUCKET": "my-test-bucket"}):
            # Reload _S3_BUCKET by patching the module-level variable
            with patch("app.mysql._S3_BUCKET", "my-test-bucket"):
                result = self._run(app, ExtractionInput(output_path=""), info)
        assert result.storage_bucket == "my-test-bucket"

    def test_connection_qualified_name_propagated(self):
        """connection_qualified_name from base SqlApp.run() is forwarded correctly."""
        from application_sdk.contracts.types import ConnectionAttributes, ConnectionRef
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()

        conn = ConnectionRef(
            attributes=ConnectionAttributes(qualified_name="default/mysql/123")
        )
        result = self._run(app, ExtractionInput(connection=conn, output_path=""), info)
        assert result.connection_qualified_name == "default/mysql/123"
