"""Unit tests for MySQLApp (v3 SqlApp)."""

from __future__ import annotations

import pytest

from app.constants import DATABASE_PLACEHOLDER
from app.mysql import MySQLApp


class TestMySQLAppClassAttrs:
    """Verify class-level configuration."""

    def test_sql_client_class_set(self):
        from app.client import SQLClient

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
        assert result["attributes"]["tenantId"] == "default"

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
        assert result["relationshipAttributes"]["database"]["typeName"] == "Database"

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
        assert result["relationshipAttributes"]["atlanSchema"]["typeName"] == "Schema"

    def test_map_table_view(self, app, connection_qn):
        """Views are returned as typeName=View based on table_kind."""
        record = {
            "table_catalog": "def",
            "table_schema": "mydb",
            "table_name": "active_users_view",
            "table_kind": "VIEW",
            "view_definition": "SELECT * FROM users WHERE active=1",
            "remarks": "Currently active users",
        }
        result = app.map_table(record, connection_qn)
        assert result["typeName"] == "View"
        assert result["attributes"]["name"] == "active_users_view"
        assert result["attributes"]["definition"] == (
            "CREATE OR REPLACE VIEW active_users_view AS SELECT * FROM users WHERE active=1"
        )
        # description comes from TABLE_COMMENT (aliased "remarks" by
        # extract_table.sql) — views are just as capable of having a real
        # description as tables are, it's not a View-exclusive marker.
        assert result["attributes"]["description"] == "Currently active users"
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
        assert result["relationshipAttributes"]["table"]["typeName"] == "Table"
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
        assert "view" in result["relationshipAttributes"]
        assert result["relationshipAttributes"]["view"]["typeName"] == "View"
        assert "table" not in result["relationshipAttributes"]
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

    def test_description_from_remarks(self, app, connection_qn):
        """description comes from ROUTINE_COMMENT (aliased 'remarks')."""
        record = {
            "procedure_catalog": "def",
            "procedure_schema": "atlan",
            "procedure_name": "count_rows",
            "procedure_definition": "BEGIN SELECT COUNT(*) FROM bigtable; END",
            "procedure_type": "PROCEDURE",
            "remarks": "Counts rows in the big table",
        }
        result = app.map_procedure(record, connection_qn)
        assert result["attributes"]["description"] == "Counts rows in the big table"

    def test_description_empty_when_no_remarks(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["attributes"]["description"] == ""

    def test_schema_ref(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        schema_ref = result["relationshipAttributes"]["atlanSchema"]
        assert schema_ref["typeName"] == "Schema"
        assert schema_ref["uniqueAttributes"]["qualifiedName"] == (
            "default/mysql/123/def/atlan"
        )

    def test_connector_name(self, app, basic_record, connection_qn):
        result = app.map_procedure(basic_record, connection_qn)
        assert result["attributes"]["connectorName"] == "mysql"

    def test_tenant_id(self, app, basic_record, connection_qn):
        from app.constants import TENANT_ID

        result = app.map_procedure(basic_record, connection_qn)
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
            PrimeAuthOutput,
        )

        # SDK v3.12+: each extract_* returns
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
            # SDK internal-ref: SqlApp.run() now awaits prime_sql_auth before
            # the parallel extract fan-out. The real prime task opens a
            # SQL connection — patch it out for these run() tests since
            # they're about output-prefix derivation, not the prime
            # itself (the prime has its own dedicated coverage in
            # application-sdk's tests/unit/templates/test_sql_app.py).
            patch.object(
                MySQLApp,
                "prime_sql_auth",
                new=AsyncMock(return_value=PrimeAuthOutput(duration_ms=1.0)),
            ),
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
            patch.object(MySQLApp, "upload", new=AsyncMock(return_value=MagicMock())),
        ):
            return asyncio.run(app.run(input_))

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


class TestEpochMs:
    """`_epoch_ms` best-effort coercion — malformed input returns None; genuine
    non-coercion bugs are not swallowed."""

    def test_none_returns_none(self):
        from app.mysql import _epoch_ms

        assert _epoch_ms(None) is None

    def test_int_passthrough(self):
        from app.mysql import _epoch_ms

        assert _epoch_ms(1_700_000_000_000) == 1_700_000_000_000

    def test_valid_timestamp_string(self):
        from app.mysql import _epoch_ms

        assert _epoch_ms("2021-01-01T00:00:00Z") == 1_609_459_200_000

    @pytest.mark.parametrize("bad", ["not-a-date", object(), [1, 2], {}])
    def test_malformed_input_returns_none(self, bad):
        """ValueError (incl. DateParseError) / TypeError from pd.Timestamp -> None.
        (Ints/floats take the passthrough branch and never reach pd.Timestamp.)"""
        from app.mysql import _epoch_ms

        assert _epoch_ms(bad) is None
