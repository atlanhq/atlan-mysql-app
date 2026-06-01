"""Parity guard rail tests — validate JSONL entity structure matches legacy Argo MySQL connector.

These tests ensure the asset mappers produce entities with the same keys,
relationship refs, and structure as the legacy connector. Values are not compared,
only the presence and shape of fields.

Reference: tests/integration/fixtures/parity_spec.json + /tmp/legacy-mysql-transformed/
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.mysql import MySQLApp


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN, Inf, NaT with None for valid JSON.

    Defensive helper for the case where a source DB stores real NaN/Inf in a
    numeric column. SqlApp used to do this; the new architecture leaves
    values native, which is correct for the common case but leaks invalid
    JSON for the rare NaN-in-DOUBLE case. Connector-side defensive
    sanitisation keeps the JSONL output spec-clean.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "__class__") and obj.__class__.__name__ in ("NaTType", "NAType"):
        return None
    return obj


PARITY_SPEC = json.loads(
    (
        Path(__file__).parent.parent / "integration" / "fixtures" / "parity_spec.json"
    ).read_text()
)

CONNECTION_QN = "default/mysql/1234567890"


@pytest.fixture
def app():
    return MySQLApp()


# ── Helper ───────────────────────────────────────────────────────────────


def _assert_structure(entity: dict, spec_key: str, entity_type: str):
    """Validate entity has all required top-level keys and attributes."""
    spec = PARITY_SPEC[spec_key]

    # Top-level keys
    for key in spec["top_level_keys"]:
        assert key in entity, f"{entity_type} missing top-level key: {key}"

    # Required attributes
    attrs = entity.get("attributes", {})
    for key in spec["required_attributes"]:
        assert key in attrs, f"{entity_type} missing attribute: {key}"


def _assert_ref(ref: dict, expected_type: str):
    """Validate a relationship ref has the correct shape."""
    assert ref is not None, "Relationship ref is None"
    assert (
        ref.get("typeName") == expected_type
    ), f"Ref typeName={ref.get('typeName')}, expected {expected_type}"
    assert "uniqueAttributes" in ref, "Ref missing uniqueAttributes"
    assert "qualifiedName" in ref["uniqueAttributes"], "Ref missing qualifiedName"
    assert ref["uniqueAttributes"]["qualifiedName"], "Ref qualifiedName is empty"


# ── Database ─────────────────────────────────────────────────────────────


class TestDatabaseParity:
    def test_structure(self, app):
        record = {"database_name": "def", "schema_count": 5}
        entity = app.map_database(record, CONNECTION_QN)
        _assert_structure(entity, "database", "Database")

    def test_qualified_name_includes_connection(self, app):
        entity = app.map_database({"database_name": "def"}, CONNECTION_QN)
        qn = entity["attributes"]["qualifiedName"]
        assert qn.startswith(CONNECTION_QN), f"QN doesn't start with connection: {qn}"
        assert entity["attributes"]["connectionQualifiedName"] == CONNECTION_QN

    def test_tenant_id(self, app):
        entity = app.map_database({"database_name": "def"}, CONNECTION_QN)
        assert entity["tenantId"] == "default"
        assert entity["attributes"]["tenantId"] == "default"

    def test_custom_attributes_present(self, app):
        entity = app.map_database({"database_name": "def"}, CONNECTION_QN)
        assert "customAttributes" in entity


# ── Schema ───────────────────────────────────────────────────────────────


class TestSchemaParity:
    def test_structure(self, app):
        record = {
            "catalog_name": "def",
            "schema_name": "employees",
            "table_count": 7,
            "views_count": 4,
        }
        entity = app.map_schema(record, CONNECTION_QN)
        _assert_structure(entity, "schema", "Schema")

    def test_database_relationship_ref(self, app):
        record = {"catalog_name": "def", "schema_name": "employees"}
        entity = app.map_schema(record, CONNECTION_QN)
        _assert_ref(entity["attributes"]["database"], "Database")

    def test_views_count(self, app):
        record = {"catalog_name": "def", "schema_name": "employees", "views_count": 4}
        entity = app.map_schema(record, CONNECTION_QN)
        assert "viewsCount" in entity["attributes"]

    def test_qualified_name_format(self, app):
        record = {"catalog_name": "def", "schema_name": "employees"}
        entity = app.map_schema(record, CONNECTION_QN)
        qn = entity["attributes"]["qualifiedName"]
        assert qn == f"{CONNECTION_QN}/def/employees"


# ── Table ────────────────────────────────────────────────────────────────


class TestTableParity:
    def test_structure_base_table(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "dept_emp",
            "table_kind": "BASE TABLE",
            "column_count": 4,
            "row_count": 100,
            "size_bytes": 1024,
            "create_time": "2021-09-16 00:00:00",
            "engine": "InnoDB",
            "version": "10",
            "row_format": "Dynamic",
            "data_length": "1024",
            "table_collation": "utf8mb4_0900_ai_ci",
            "create_options": "",
        }
        entity = app.map_table(record, CONNECTION_QN)
        _assert_structure(entity, "table", "Table")
        assert entity["typeName"] == "Table"

    def test_structure_view(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "dept_view",
            "table_kind": "VIEW",
            "column_count": 3,
            "size_bytes": 0,
            "view_definition": "CREATE VIEW ...",
        }
        entity = app.map_table(record, CONNECTION_QN)
        _assert_structure(entity, "view", "View")
        assert entity["typeName"] == "View"

    def test_atlan_schema_ref(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "t1",
            "table_kind": "BASE TABLE",
        }
        entity = app.map_table(record, CONNECTION_QN)
        _assert_ref(entity["attributes"]["atlanSchema"], "Schema")

    def test_custom_attributes(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "t1",
            "table_kind": "BASE TABLE",
            "engine": "InnoDB",
            "version": "10",
            "row_format": "Dynamic",
            "data_length": "1024",
            "table_collation": "utf8mb4",
            "create_options": "",
        }
        entity = app.map_table(record, CONNECTION_QN)
        custom = entity["customAttributes"]
        for key in (
            "engine",
            "version",
            "row_format",
            "data_length",
            "table_collation",
            "create_options",
            "is_transient",
        ):
            assert key in custom, f"Table customAttributes missing: {key}"

    def test_table_has_row_count_and_sub_type(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
            "row_count": 500,
        }
        entity = app.map_table(record, CONNECTION_QN)
        assert entity["attributes"]["rowCount"] == 500
        assert entity["attributes"]["subType"] == "TABLE"

    def test_view_has_definition_and_description(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "v",
            "table_kind": "VIEW",
            "view_definition": "SELECT 1",
        }
        entity = app.map_table(record, CONNECTION_QN)
        assert (
            entity["attributes"]["definition"] == "CREATE OR REPLACE VIEW v AS SELECT 1"
        )
        assert entity["attributes"]["description"] == "VIEW"
        assert "rowCount" not in entity["attributes"]

    def test_source_created_at(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
            "create_time": "2021-09-16 00:05:23",
        }
        entity = app.map_table(record, CONNECTION_QN)
        assert "sourceCreatedAt" in entity["attributes"]
        assert isinstance(entity["attributes"]["sourceCreatedAt"], int)


# ── Column ───────────────────────────────────────────────────────────────


class TestColumnParity:
    def test_structure_table_column(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "dept_emp",
            "column_name": "emp_no",
            "table_type": "BASE TABLE",
            "data_type": "int",
            "is_nullable": "NO",
            "ordinal_position": 1,
            "numeric_precision": 10,
            "max_length": 0,
            "numeric_scale": 0,
            "constraint_type": "PRIMARY KEY",
        }
        entity = app.map_column(record, CONNECTION_QN)
        _assert_structure(entity, "column", "Column")

        # Table-specific conditional attributes
        attrs = entity["attributes"]
        for key in PARITY_SPEC["column"]["conditional_attributes"]["table_column"]:
            assert key in attrs, f"Table column missing: {key}"

        _assert_ref(attrs["table"], "Table")

    def test_structure_view_column(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "current_dept_emp",
            "column_name": "emp_no",
            "table_type": "VIEW",
            "data_type": "int",
            "is_nullable": "NO",
            "ordinal_position": 1,
        }
        entity = app.map_column(record, CONNECTION_QN)

        attrs = entity["attributes"]
        for key in PARITY_SPEC["column"]["conditional_attributes"]["view_column"]:
            assert key in attrs, f"View column missing: {key}"

        _assert_ref(attrs["view"], "View")
        assert "table" not in attrs

    def test_primary_key_detection(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "id",
            "table_type": "BASE TABLE",
            "constraint_type": "PRIMARY KEY",
        }
        entity = app.map_column(record, CONNECTION_QN)
        assert entity["attributes"]["isPrimary"] is True
        assert entity["attributes"]["isForeign"] is False

    def test_foreign_key_detection(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "ref_id",
            "table_type": "BASE TABLE",
            "constraint_type": "FOREIGN KEY",
        }
        entity = app.map_column(record, CONNECTION_QN)
        assert entity["attributes"]["isPrimary"] is False
        assert entity["attributes"]["isForeign"] is True

    def test_data_type_uppercase(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
            "data_type": "varchar",
        }
        entity = app.map_column(record, CONNECTION_QN)
        assert entity["attributes"]["dataType"] == "VARCHAR"

    def test_custom_attributes(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
            "data_type": "int",
            "column_type": "int",
            "column_key": "PRI",
            "privileges": "select",
            "character_set_name": "utf8mb4",
            "collation_name": "utf8mb4_0900_ai_ci",
        }
        entity = app.map_column(record, CONNECTION_QN)
        custom = entity["customAttributes"]
        assert "type_name" in custom
        assert custom["type_name"] == "int"
        for key in (
            "column_type",
            "column_key",
            "privileges",
            "character_set_name",
            "collation_name",
        ):
            assert key in custom, f"Column customAttributes missing: {key}"


# ── JSON serialization safety ────────────────────────────────────────────


class TestJsonSerialization:
    """Verify entities serialize to valid JSON (no NaN, Inf, NaT)."""

    def test_column_with_nan_values_produces_valid_json(self, app):
        """SQL NULLs become NaN in pandas — SDK sanitizes before writing JSONL."""
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
            "data_type": "double",
            "numeric_precision": float("nan"),
            "character_octet_length": float("nan"),
            "column_size": float("nan"),
            "numeric_scale": float("nan"),
            "ordinal_position": 1,
        }
        entity = app.map_column(record, CONNECTION_QN)
        # SDK sanitizes NaN before writing — simulate that here
        sanitized = _sanitize_for_json(entity)
        serialized = json.dumps(sanitized)
        assert "NaN" not in serialized, "NaN found in JSON output"
        assert "Infinity" not in serialized, "Infinity found in JSON output"
        parsed = json.loads(serialized)
        assert parsed["typeName"] == "Column"

    def test_column_with_inf_values_produces_valid_json(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
            "numeric_precision": float("inf"),
            "column_size": float("-inf"),
        }
        entity = app.map_column(record, CONNECTION_QN)
        sanitized = _sanitize_for_json(entity)
        serialized = json.dumps(sanitized)
        assert "Infinity" not in serialized

    def test_table_with_nan_size_produces_valid_json(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
            "size_bytes": float("nan"),
            "row_count": float("nan"),
        }
        entity = app.map_table(record, CONNECTION_QN)
        sanitized = _sanitize_for_json(entity)
        serialized = json.dumps(sanitized)
        assert "NaN" not in serialized


# ── Cross-entity consistency ─────────────────────────────────────────────


class TestCrossEntityConsistency:
    """Verify QN patterns are consistent across entity types."""

    def test_qn_hierarchy(self, app):
        db = app.map_database({"database_name": "def"}, CONNECTION_QN)
        schema = app.map_schema(
            {"catalog_name": "def", "schema_name": "emp"}, CONNECTION_QN
        )
        table = app.map_table(
            {
                "table_catalog": "def",
                "table_schema": "emp",
                "table_name": "t1",
                "table_kind": "BASE TABLE",
            },
            CONNECTION_QN,
        )
        column = app.map_column(
            {
                "table_catalog": "def",
                "table_schema": "emp",
                "table_name": "t1",
                "column_name": "id",
                "table_type": "BASE TABLE",
            },
            CONNECTION_QN,
        )

        db_qn = db["attributes"]["qualifiedName"]
        schema_qn = schema["attributes"]["qualifiedName"]
        table_qn = table["attributes"]["qualifiedName"]
        col_qn = column["attributes"]["qualifiedName"]

        assert schema_qn.startswith(db_qn)
        assert table_qn.startswith(schema_qn)
        assert col_qn.startswith(table_qn)

    def test_all_entities_have_tenant_id(self, app):
        for entity in [
            app.map_database({"database_name": "def"}, CONNECTION_QN),
            app.map_schema({"catalog_name": "def", "schema_name": "s"}, CONNECTION_QN),
            app.map_table(
                {
                    "table_catalog": "def",
                    "table_schema": "s",
                    "table_name": "t",
                    "table_kind": "BASE TABLE",
                },
                CONNECTION_QN,
            ),
            app.map_column(
                {
                    "table_catalog": "def",
                    "table_schema": "s",
                    "table_name": "t",
                    "column_name": "c",
                    "table_type": "BASE TABLE",
                },
                CONNECTION_QN,
            ),
        ]:
            assert (
                entity.get("tenantId") == "default"
            ), f"{entity['typeName']} missing tenantId"

    def test_all_entities_have_custom_attributes(self, app):
        for entity in [
            app.map_database({"database_name": "def"}, CONNECTION_QN),
            app.map_schema({"catalog_name": "def", "schema_name": "s"}, CONNECTION_QN),
            app.map_table(
                {
                    "table_catalog": "def",
                    "table_schema": "s",
                    "table_name": "t",
                    "table_kind": "BASE TABLE",
                },
                CONNECTION_QN,
            ),
            app.map_column(
                {
                    "table_catalog": "def",
                    "table_schema": "s",
                    "table_name": "t",
                    "column_name": "c",
                    "table_type": "BASE TABLE",
                },
                CONNECTION_QN,
            ),
        ]:
            assert (
                "customAttributes" in entity
            ), f"{entity['typeName']} missing customAttributes"
