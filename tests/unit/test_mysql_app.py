"""Unit tests for MySQLApp (v3 SqlApp)."""

from __future__ import annotations

import pytest

from app.constants import DATABASE_PLACEHOLDER
from app.mysql import MySQLApp


class TestMySQLAppClassAttrs:
    """Verify class-level configuration."""

    def test_preflight_gate_is_hard_on_every_run_mode(self):
        """The gate enforces on every path, SDR included.

        Pinned because `_resolve_gate_enforcement` falls back to soft on any
        value it does not recognise, so a revert or a malformed literal here
        stops the gate blocking without failing a single other test.
        """
        assert MySQLApp.preflight_gate_mode == "hard"

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

    def _run(self, app, input_, wf_info, upload_refs_output=None):
        """Run MySQLApp.run() with all SQL tasks mocked out.

        ``upload_refs_output`` overrides what the mocked ``upload_refs`` returns,
        so a test can drive the empty-delivery case — the one case where the
        delivered prefix and ``base_result.transformed_data_prefix`` differ.
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from application_sdk.contracts.storage import UploadRefsOutput
        from application_sdk.contracts.types import FileReference
        from application_sdk.templates.contracts.sql_metadata import (
            ExtractionTaskOutput,
            PrimeAuthOutput,
            TransformOutput,
        )

        run_prefix = (
            f"artifacts/apps/mysql/workflows/{wf_info.workflow_id}/{wf_info.run_id}"
        )

        # SDK v3.12+: each extract_* returns
        # ``ExtractionTaskOutput`` with a ``raw_file: FileReference | None``
        # field. ``run()`` reads ``.raw_file`` and threads it into the
        # matching transform via ``build_transform_input``, which
        # Pydantic-validates the ref against ``FileReference`` —
        # MagicMock auto-attrs would fail that validation. Use real
        # ``ExtractionTaskOutput`` instances with ``raw_file=None``.
        def _extract_result(entity: str, count: int) -> ExtractionTaskOutput:
            return ExtractionTaskOutput(
                typename=entity, total_record_count=count, raw_file=None
            )

        # FND-1790: SqlApp.run() collects each transform's ``transformed_file``
        # and MySQLApp.run() hands the collected declaration to upload_refs().
        # A MagicMock's auto-attr would sail through the ``is not None`` check
        # and then fail FileReference validation inside VerifyRefsInput, so the
        # transforms have to return real ``TransformOutput`` values here.
        def _transform_result(entity: str, count: int) -> TransformOutput:
            return TransformOutput(
                typename=entity,
                total_record_count=count,
                transformed_file=FileReference(
                    storage_path=f"{run_prefix}/transformed/{entity}/entities.json",
                    file_count=1,
                ),
            )

        upload_refs_mock = AsyncMock(
            return_value=upload_refs_output
            if upload_refs_output is not None
            else UploadRefsOutput(prefix=f"{run_prefix}/transformed")
        )
        verify_refs_mock = AsyncMock(return_value=MagicMock())

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
                MySQLApp,
                "transform_databases",
                new=AsyncMock(return_value=_transform_result("database", 1)),
            ),
            patch.object(
                MySQLApp,
                "transform_schemas",
                new=AsyncMock(return_value=_transform_result("schema", 1)),
            ),
            patch.object(
                MySQLApp,
                "transform_tables",
                new=AsyncMock(return_value=_transform_result("table", 2)),
            ),
            patch.object(
                MySQLApp,
                "transform_columns",
                new=AsyncMock(return_value=_transform_result("column", 5)),
            ),
            patch.object(
                MySQLApp,
                "transform_procedures",
                new=AsyncMock(return_value=_transform_result("procedure", 1)),
            ),
            patch.object(MySQLApp, "resolve_credential_ref", return_value=None),
            # verify_refs is the framework task SqlApp.run() uses to assert its
            # own declaration against the deployment store; upload_refs is the
            # fan-in MySQLApp.run() uses to deliver that declaration upstream.
            # Both are store round-trips — out of scope for these output-prefix
            # tests, and both have dedicated coverage in application-sdk.
            patch.object(MySQLApp, "verify_refs", new=verify_refs_mock),
            patch.object(MySQLApp, "upload_refs", new=upload_refs_mock),
        ):
            result = asyncio.run(app.run(input_))
            self.last_upload_refs = upload_refs_mock
            self.last_verify_refs = verify_refs_mock
            return result

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

    # ── FND-1790: fan-in by declaration, not by directory scan ──────────

    def test_upload_refs_declares_every_transform_including_procedures(self):
        """The declaration handed to upload_refs covers all five entities.

        The procedure transform runs in MySQLApp.run(), not SqlApp.run(), so its
        ref is absent from base_result.transformed_files and has to be appended
        explicitly. Dropping it would lose every procedure — silently, because
        the ref-based upload has no directory to fall back on.
        """
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        self._run(app, ExtractionInput(output_path=""), info)

        sent = self.last_upload_refs.await_args.args[0]
        leaves = {
            declared.ref.storage_path.rsplit("/transformed/", 1)[-1]
            for declared in sent.files
        }
        assert leaves == {
            "database/entities.json",
            "schema/entities.json",
            "table/entities.json",
            "column/entities.json",
            "procedure/entities.json",
        }

    def test_procedure_ref_is_verified_not_just_declared(self):
        """The procedure ref must appear in a verify_refs call, not only in the output.

        super().run() verifies the four refs it drove and then returns, so a ref
        appended afterwards is asserted by nobody. Concatenating by hand would
        still put five entries in transformed_files — right data, absent proof —
        which is why the entity count alone is not sufficient coverage here.
        finalize_extraction() re-verifies the whole concatenated declaration.

        This is the only run() test that binds an ``_context``. finalize_extraction
        skips verification entirely when there is none — correctly, since without
        a context there is no worker, no interceptor, and nothing persisted to
        verify — so an unbound app would make this assertion unprovable. The other
        run() tests stay context-less on purpose: that is the path that proves the
        no-worker case still assembles and returns its declaration.
        """
        from application_sdk.app.context import AppContext
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        app._context = AppContext(
            app_name="mysql",
            app_version="1",
            run_id="run-test-456",
            # Non-None so the guard treats this as running under a worker;
            # verify_refs itself is mocked, so the store is never touched.
            _storage=object(),  # type: ignore[arg-type]
        )
        info = self._mock_workflow_info()
        self._run(app, ExtractionInput(output_path=""), info)

        verified = {
            ref.storage_path
            for call in self.last_verify_refs.await_args_list
            for ref in call.args[0].refs
        }
        assert any("/transformed/procedure/" in path for path in verified), (
            "the procedure ref was never passed to verify_refs — it is being "
            "handed downstream on the strength of the declaration alone"
        )

    def test_upload_refs_preserves_publish_key_shape(self):
        """source_prefix equals the destination prefix, so keys are unchanged.

        The refs already carry <run>/transformed/<entity>/entities.json. Stripping
        source_prefix yields <entity>/entities.json, which lands back under the
        same prefix — publish reads the exact keys it read before the switch.
        """
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        self._run(app, ExtractionInput(output_path=""), info)

        sent = self.last_upload_refs.await_args.args[0]
        assert sent.source_prefix == sent.prefix
        assert sent.prefix.endswith("/transformed")

    def test_empty_delivery_yields_an_empty_transformed_data_prefix(self):
        """An empty delivery must propagate as "", not as the input prefix.

        upload_refs answers an empty declaration with an empty prefix on purpose:
        a prefix naming an empty tree reads to publish as "everything was deleted
        at source", whereas an empty prefix is a no-op. Returning
        base_result.transformed_data_prefix instead would defeat that.

        Driving the empty case is what makes this test discriminate at all — on a
        normal run upload_refs echoes back the prefix it was given, so the two
        candidate expressions produce the same string and an assertion comparing
        them would pass either way.
        """
        from application_sdk.contracts.storage import UploadRefsOutput
        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        result = self._run(
            app,
            ExtractionInput(output_path=""),
            info,
            upload_refs_output=UploadRefsOutput(),
        )

        assert result.transformed_data_prefix == "", (
            "run() returned a non-empty transformed_data_prefix for a delivery "
            "that landed nothing — publish would diff against an empty tree and "
            "archive every asset as removed from source"
        )

    def test_transformed_tree_is_never_uploaded_by_directory_scan(self):
        """App.upload() must not be used for the transformed tree.

        Guards the FND-1790 regression directly: a local-path upload walks only
        the pod it runs on, so on a fanned-out run it hands publish a short tree
        that is indistinguishable from a small one.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from application_sdk.templates.contracts.sql_metadata import ExtractionInput

        app = self._make_app()
        info = self._mock_workflow_info()
        upload_mock = AsyncMock(return_value=MagicMock())
        with patch.object(MySQLApp, "upload", new=upload_mock):
            self._run(app, ExtractionInput(output_path=""), info)

        assert not upload_mock.await_args_list, (
            "MySQLApp.run() uploaded by local path — the transformed hand-off "
            "must go through upload_refs() so it works when the transform "
            "activities ran on other pods"
        )


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
