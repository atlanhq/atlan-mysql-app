"""Structural guard rail tests for the pyatlan_v9 asset-mapper (.creator()) output.

These tests ensure the asset mappers produce entities with the expected keys,
relationship refs, and structure for the native pyatlan_v9 wire shape (BLDX-1492
asset-mapper migration) — ``tenantId``/``status`` are not duplicated at the top
level the way the legacy hand-rolled dict shape did. Values are not compared,
only the presence and shape of fields.

Relationship refs are read through :func:`tests.wire.rels_of`, which accepts
either envelope position: the SDK flattens refs into ``attributes`` from 3.36.0
(FND-2137), and before that they sat under a top-level ``relationshipAttributes``
key. The refs themselves are identical either way, so these tests pin them under
both SDKs; ``test_refs_live_in_exactly_one_place`` pins which envelope is
actually in force, and that a ref is never lost or duplicated across the two.

Reference: tests/integration/fixtures/parity_spec.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.mysql import MySQLApp
from tests.wire import rels_of, wire


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


SHAPE_SPEC = json.loads(
    (
        Path(__file__).parent.parent / "integration" / "fixtures" / "parity_spec.json"
    ).read_text()
)

CONNECTION_QN = "default/mysql/1234567890"


@pytest.fixture
def app():
    return MySQLApp()


# ── Helper ───────────────────────────────────────────────────────────────


def assert_structure(entity: dict, spec_key: str, entity_type: str):
    """Validate entity has all required top-level keys, attributes, and relationships."""
    spec = SHAPE_SPEC[spec_key]

    # Top-level keys
    for key in spec["top_level_keys"]:
        assert key in entity, f"{entity_type} missing top-level key: {key}"

    # Required attributes
    attrs = entity.get("attributes", {})
    for key in spec["required_attributes"]:
        assert key in attrs, f"{entity_type} missing attribute: {key}"

    # Required relationships (in whichever envelope position is in force)
    rels = rels_of(entity)
    for key in spec.get("required_relationships", []):
        assert key in rels, f"{entity_type} missing relationship: {key}"


def assert_ref(ref: dict, expected_type: str):
    """Validate a relationship ref has the correct shape."""
    assert ref is not None, "Relationship ref is None"
    assert ref.get("typeName") == expected_type, (
        f"Ref typeName={ref.get('typeName')}, expected {expected_type}"
    )
    assert "uniqueAttributes" in ref, "Ref missing uniqueAttributes"
    assert "qualifiedName" in ref["uniqueAttributes"], "Ref missing qualifiedName"
    assert ref["uniqueAttributes"]["qualifiedName"], "Ref qualifiedName is empty"


# ── Database ─────────────────────────────────────────────────────────────


class TestDatabaseParity:
    def test_structure(self, app):
        record = {"database_name": "def", "schema_count": 5}
        entity = wire(app.map_database(record, CONNECTION_QN))
        assert_structure(entity, "database", "Database")

    def test_qualified_name_includes_connection(self, app):
        entity = wire(app.map_database({"database_name": "def"}, CONNECTION_QN))
        qn = entity["attributes"]["qualifiedName"]
        assert qn.startswith(CONNECTION_QN), f"QN doesn't start with connection: {qn}"
        assert entity["attributes"]["connectionQualifiedName"] == CONNECTION_QN

    def test_tenant_id(self, app):
        entity = wire(app.map_database({"database_name": "def"}, CONNECTION_QN))
        assert entity["attributes"]["tenantId"] == "default"


# ── Schema ───────────────────────────────────────────────────────────────


class TestSchemaParity:
    def test_structure(self, app):
        record = {
            "catalog_name": "def",
            "schema_name": "employees",
            "table_count": 7,
            "views_count": 4,
        }
        entity = wire(app.map_schema(record, CONNECTION_QN))
        assert_structure(entity, "schema", "Schema")

    def test_database_relationship_ref(self, app):
        record = {"catalog_name": "def", "schema_name": "employees"}
        entity = wire(app.map_schema(record, CONNECTION_QN))
        assert_ref(rels_of(entity)["database"], "Database")

    def test_views_count(self, app):
        record = {"catalog_name": "def", "schema_name": "employees", "views_count": 4}
        entity = wire(app.map_schema(record, CONNECTION_QN))
        assert "viewsCount" in entity["attributes"]

    def test_qualified_name_format(self, app):
        record = {"catalog_name": "def", "schema_name": "employees"}
        entity = wire(app.map_schema(record, CONNECTION_QN))
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
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert_structure(entity, "table", "Table")
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
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert_structure(entity, "view", "View")
        assert entity["typeName"] == "View"

    def test_atlan_schema_ref(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "employees",
            "table_name": "t1",
            "table_kind": "BASE TABLE",
        }
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert_ref(rels_of(entity)["atlanSchema"], "Schema")

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
        entity = wire(app.map_table(record, CONNECTION_QN))
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
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert entity["attributes"]["rowCount"] == 500
        assert entity["attributes"]["subType"] == "TABLE"

    def test_table_has_no_definition(self, app):
        """'definition' is genuinely View-only on the pyatlan_v9 model — Table has
        no such field at all, unlike 'description' (present on every asset type,
        just not populated for tables by this mapper today)."""
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
        }
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert "definition" not in entity["attributes"]

    def test_view_has_definition(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "v",
            "table_kind": "VIEW",
            "view_definition": "SELECT 1",
        }
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert (
            entity["attributes"]["definition"] == "CREATE OR REPLACE VIEW v AS SELECT 1"
        )
        assert "rowCount" not in entity["attributes"]

    def test_table_and_view_description_from_remarks(self, app):
        """'description' comes from TABLE_COMMENT (aliased 'remarks' by
        extract_table.sql) for both Table and View — not a View-only marker."""
        table_record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
            "remarks": "Orders placed by customers",
        }
        table_entity = wire(app.map_table(table_record, CONNECTION_QN))
        assert table_entity["attributes"]["description"] == "Orders placed by customers"

        view_record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "v",
            "table_kind": "VIEW",
            "remarks": "Active orders only",
        }
        view_entity = wire(app.map_table(view_record, CONNECTION_QN))
        assert view_entity["attributes"]["description"] == "Active orders only"

    def test_table_description_empty_when_no_remarks(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
        }
        entity = wire(app.map_table(record, CONNECTION_QN))
        assert entity["attributes"]["description"] == ""

    def test_source_created_at(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "table_kind": "BASE TABLE",
            "create_time": "2021-09-16 00:05:23",
        }
        entity = wire(app.map_table(record, CONNECTION_QN))
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
        entity = wire(app.map_column(record, CONNECTION_QN))
        assert_structure(entity, "column", "Column")

        # Table-specific conditional attributes
        attrs = entity["attributes"]
        for key in SHAPE_SPEC["column"]["conditional_attributes"]["table_column"]:
            assert key in attrs, f"Table column missing: {key}"

        assert_ref(rels_of(entity)["table"], "Table")

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
        entity = wire(app.map_column(record, CONNECTION_QN))

        attrs = entity["attributes"]
        for key in SHAPE_SPEC["column"]["conditional_attributes"]["view_column"]:
            assert key in attrs, f"View column missing: {key}"

        assert_ref(rels_of(entity)["view"], "View")
        assert "table" not in rels_of(entity)

    def test_primary_key_detection(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "id",
            "table_type": "BASE TABLE",
            "constraint_type": "PRIMARY KEY",
        }
        entity = wire(app.map_column(record, CONNECTION_QN))
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
        entity = wire(app.map_column(record, CONNECTION_QN))
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
        entity = wire(app.map_column(record, CONNECTION_QN))
        assert entity["attributes"]["dataType"] == "VARCHAR"

    def test_description_from_remarks(self, app):
        """description comes from COLUMN_COMMENT (aliased 'remarks')."""
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
            "remarks": "Primary identifier",
        }
        entity = wire(app.map_column(record, CONNECTION_QN))
        assert entity["attributes"]["description"] == "Primary identifier"

    def test_description_empty_when_no_remarks(self, app):
        record = {
            "table_catalog": "def",
            "table_schema": "s",
            "table_name": "t",
            "column_name": "c",
            "table_type": "BASE TABLE",
        }
        entity = wire(app.map_column(record, CONNECTION_QN))
        assert entity["attributes"]["description"] == ""

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
        entity = wire(app.map_column(record, CONNECTION_QN))
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


# ── Envelope invariant ───────────────────────────────────────────────────


class TestEnvelopeInvariant:
    """Pin *where* relationship refs live, now that the ref assertions accept both.

    Every other ref assertion in this file goes through
    :func:`tests.wire.rels_of`, which reads either envelope position so the suite
    is green under both the current SDK and the flattened envelope (FND-2137).
    That widening on its own could no longer notice an accidental envelope flip
    — the exact failure FND-2137 exists to prevent — so the shape assertion moves
    here rather than disappearing.

    Both genuinely bad states fail this test: a ref in neither position has been
    lost, and a ref in both would double-write the relationship. Which of the two
    good positions is in force is deliberately not asserted — that is the SDK's
    declared policy to choose, and this test outlives the transition.
    """

    @pytest.mark.parametrize(
        ("mapper", "record", "ref"),
        [
            (
                "map_table",
                {
                    "table_catalog": "def",
                    "table_schema": "employees",
                    "table_name": "dept_emp",
                    "table_kind": "BASE TABLE",
                },
                "atlanSchema",
            ),
            (
                "map_column",
                {
                    "table_catalog": "def",
                    "table_schema": "employees",
                    "table_name": "dept_emp",
                    "column_name": "emp_no",
                    "table_type": "BASE TABLE",
                },
                "table",
            ),
            (
                "map_column",
                {
                    "table_catalog": "def",
                    "table_schema": "employees",
                    "table_name": "current_dept_emp",
                    "column_name": "emp_no",
                    "table_type": "VIEW",
                },
                "view",
            ),
        ],
        ids=["table.atlanSchema", "column.table", "column.view"],
    )
    def test_refs_live_in_exactly_one_place(self, app, mapper, record, ref):
        entity = wire(getattr(app, mapper)(record, CONNECTION_QN))
        nested = ref in entity.get("relationshipAttributes", {})
        flat = ref in entity["attributes"]
        assert nested != flat, (
            f"{entity['typeName']}.{ref} must appear in exactly one envelope "
            f"position (relationshipAttributes={nested}, attributes={flat})"
        )


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
        entity = wire(app.map_column(record, CONNECTION_QN))
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
        entity = wire(app.map_column(record, CONNECTION_QN))
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
        entity = wire(app.map_table(record, CONNECTION_QN))
        sanitized = _sanitize_for_json(entity)
        serialized = json.dumps(sanitized)
        assert "NaN" not in serialized


# ── Cross-entity consistency ─────────────────────────────────────────────


class TestCrossEntityConsistency:
    """Verify QN patterns are consistent across entity types."""

    def test_qn_hierarchy(self, app):
        db = wire(app.map_database({"database_name": "def"}, CONNECTION_QN))
        schema = wire(
            app.map_schema({"catalog_name": "def", "schema_name": "emp"}, CONNECTION_QN)
        )
        table = wire(
            app.map_table(
                {
                    "table_catalog": "def",
                    "table_schema": "emp",
                    "table_name": "t1",
                    "table_kind": "BASE TABLE",
                },
                CONNECTION_QN,
            )
        )
        column = wire(
            app.map_column(
                {
                    "table_catalog": "def",
                    "table_schema": "emp",
                    "table_name": "t1",
                    "column_name": "id",
                    "table_type": "BASE TABLE",
                },
                CONNECTION_QN,
            )
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
            wire(app.map_database({"database_name": "def"}, CONNECTION_QN)),
            wire(
                app.map_schema(
                    {"catalog_name": "def", "schema_name": "s"}, CONNECTION_QN
                )
            ),
            wire(
                app.map_table(
                    {
                        "table_catalog": "def",
                        "table_schema": "s",
                        "table_name": "t",
                        "table_kind": "BASE TABLE",
                    },
                    CONNECTION_QN,
                )
            ),
            wire(
                app.map_column(
                    {
                        "table_catalog": "def",
                        "table_schema": "s",
                        "table_name": "t",
                        "column_name": "c",
                        "table_type": "BASE TABLE",
                    },
                    CONNECTION_QN,
                )
            ),
        ]:
            assert entity["attributes"].get("tenantId") == "default", (
                f"{entity['typeName']} missing tenantId"
            )

    def test_table_and_column_have_custom_attributes(self, app):
        """Only Table/Column mappers populate custom_attributes on the pyatlan_v9
        asset — Database/Schema/Procedure have no MySQL-specific metadata to carry,
        so they legitimately omit the key (unlike the legacy shape, which always
        included an empty ``customAttributes: {}``)."""
        for entity in [
            wire(
                app.map_table(
                    {
                        "table_catalog": "def",
                        "table_schema": "s",
                        "table_name": "t",
                        "table_kind": "BASE TABLE",
                    },
                    CONNECTION_QN,
                )
            ),
            wire(
                app.map_column(
                    {
                        "table_catalog": "def",
                        "table_schema": "s",
                        "table_name": "t",
                        "column_name": "c",
                        "table_type": "BASE TABLE",
                    },
                    CONNECTION_QN,
                )
            ),
        ]:
            assert "customAttributes" in entity, (
                f"{entity['typeName']} missing customAttributes"
            )
