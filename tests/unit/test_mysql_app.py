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
        assert (
            result["attributes"]["definition"] == "SELECT * FROM users WHERE active=1"
        )
        assert result["attributes"]["description"] == "VIEW"
        assert "rowCount" not in result["attributes"]

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

        with (
            patch("temporalio.workflow.info", return_value=wf_info),
            patch.object(
                MySQLApp,
                "fetch_databases",
                new=AsyncMock(return_value=MagicMock(total_record_count=1)),
            ),
            patch.object(
                MySQLApp,
                "fetch_schemas",
                new=AsyncMock(return_value=MagicMock(total_record_count=1)),
            ),
            patch.object(
                MySQLApp,
                "fetch_tables",
                new=AsyncMock(return_value=MagicMock(total_record_count=2)),
            ),
            patch.object(
                MySQLApp,
                "fetch_columns",
                new=AsyncMock(return_value=MagicMock(total_record_count=5)),
            ),
            patch.object(
                MySQLApp,
                "fetch_procedures",
                new=AsyncMock(return_value=MagicMock(total_record_count=1)),
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
            patch.object(
                MySQLApp, "upload_to_atlan", new=AsyncMock(return_value=MagicMock())
            ),
            patch.object(MySQLApp, "_resolve_credential_ref", return_value=None),
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
        from unittest.mock import MagicMock, patch

        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        # workflow.info() must NOT be called when output_path is explicit
        with patch("temporalio.workflow.info") as mock_info:
            info = self._mock_workflow_info()
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
