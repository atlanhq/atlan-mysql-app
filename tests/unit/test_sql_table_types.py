"""Tables and columns must be extracted for the same set of TABLE_TYPEs."""

import re
from pathlib import Path

SQL = Path(__file__).resolve().parents[2] / "app" / "sql"
TYPE_LIST = re.compile(r"TABLE_TYPE\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def _types(name: str) -> set[str]:
    code = re.sub(r"/\*.*?\*/|--[^\n]*", "", (SQL / name).read_text(), flags=re.S)
    found = TYPE_LIST.findall(code)
    assert len(found) == 1, f"{name}: expected one TABLE_TYPE IN list"
    return set(re.findall(r"'([^']+)'", found[0]))


def test_system_versioned_tables_are_extracted_with_their_columns():
    table_types = _types("extract_table.sql")
    assert "SYSTEM VERSIONED" in table_types
    assert _types("extract_column.sql") == table_types
    assert _types("tables_check.sql") == table_types


def test_schema_table_count_includes_system_versioned_tables():
    sql = (SQL / "extract_schema.sql").read_text()
    assert re.search(r"TABLE_TYPE IN \([^)]*'SYSTEM VERSIONED'", sql)
