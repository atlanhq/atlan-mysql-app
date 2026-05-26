"""Shared entity metadata for parity generation, comparison, and reporting."""

from __future__ import annotations

ENTITY_TYPES = ("database", "schema", "table", "column", "procedure", "view")

RESULT_COUNT_FIELDS = {
    "database": "databases_extracted",
    "schema": "schemas_extracted",
    "table": "tables_extracted",
    "column": "columns_extracted",
    "procedure": "procedures_extracted",
    "view": "views_extracted",
}

RECORD_COUNT_FIELDS = tuple(RESULT_COUNT_FIELDS[entity] for entity in ENTITY_TYPES)

# Atlas typeName for each entity. Comparisons key off this rather than the
# emitting filename because v2 lumps Tables + Views into one ``table.jsonl``
# (with mixed ``typeName`` values) while v3 splits them into separate files.
# Grouping by ``typeName`` makes the comparison file-layout-agnostic.
ENTITY_TO_TYPENAME = {
    "database": "Database",
    "schema": "Schema",
    "table": "Table",
    "column": "Column",
    "procedure": "Procedure",
    "view": "View",
}
