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
