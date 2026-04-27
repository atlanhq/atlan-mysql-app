"""Unit tests for resolve_cloned_information_schema utility."""

import re
from pathlib import Path

import pytest

from app.activities.metadata_extraction.utils import (
    DEFAULT_INFORMATION_SCHEMA_PREFIX,
    resolve_cloned_information_schema,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SQL = (
    "SELECT * FROM {cloned_information_schema}TABLES "
    "WHERE TABLE_SCHEMA NOT IN "
    "('mysql', 'performance_schema', 'information_schema', 'sys'"
    "{cloned_schema_exclusion})"
)

MULTI_PLACEHOLDER_SQL = (
    "SELECT C.* FROM {cloned_information_schema}COLUMNS C "
    "LEFT JOIN {cloned_information_schema}TABLES T "
    "ON C.TABLE_SCHEMA = T.TABLE_SCHEMA "
    "WHERE C.TABLE_SCHEMA NOT IN "
    "('mysql', 'performance_schema', 'information_schema', 'sys'"
    "{cloned_schema_exclusion})"
)


def _make_workflow_args(strategy=None, config=None):
    args = {}
    if strategy is not None:
        args["control-config-strategy"] = strategy
    if config is not None:
        args["control-config"] = config
    return args


# ---------------------------------------------------------------------------
# Tests: default / no-config behavior
# ---------------------------------------------------------------------------


class TestDefaultBehavior:
    """When no config is set, SQL resolves to standard information_schema."""

    def test_no_args_resolves_to_information_schema(self):
        result = resolve_cloned_information_schema({}, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result
        assert "{cloned_information_schema}" not in result
        assert "{cloned_schema_exclusion}" not in result

    def test_strategy_default_ignores_config(self):
        args = _make_workflow_args(
            strategy="default",
            config='{"clonedInformationSchema": "atlan_meta"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result
        assert "atlan_meta" not in result

    def test_strategy_missing_uses_default(self):
        args = _make_workflow_args(config='{"clonedInformationSchema": "atlan_meta"}')
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_config_missing_uses_default(self):
        args = _make_workflow_args(strategy="custom")
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_empty_config_uses_default(self):
        args = _make_workflow_args(strategy="custom", config="{}")
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_config_without_cloned_key_uses_default(self):
        args = _make_workflow_args(
            strategy="custom", config='{"someOtherKey": "value"}'
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result


# ---------------------------------------------------------------------------
# Tests: cloned schema behavior
# ---------------------------------------------------------------------------


class TestClonedSchemaBehavior:
    """When clonedInformationSchema is configured, SQL uses the clone."""

    def test_cloned_schema_replaces_prefix(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "atlan_meta"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "atlan_meta.TABLES" in result
        assert "information_schema.TABLES" not in result

    def test_cloned_schema_adds_exclusion(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "atlan_meta"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert ", 'atlan_meta'" in result

    def test_multiple_placeholders_all_resolved(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "mirror_db"}',
        )
        result = resolve_cloned_information_schema(args, MULTI_PLACEHOLDER_SQL)
        assert result is not None
        assert "mirror_db.COLUMNS" in result
        assert "mirror_db.TABLES" in result
        assert "{cloned_information_schema}" not in result

    def test_config_as_dict(self):
        """Config can be passed as a dict (not just JSON string)."""
        args = _make_workflow_args(strategy="custom")
        args["control-config"] = {"clonedInformationSchema": "my_schema"}
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "my_schema.TABLES" in result

    def test_schema_name_with_underscores(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "atlan_mysql_meta_v2"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "atlan_mysql_meta_v2.TABLES" in result
        assert ", 'atlan_mysql_meta_v2'" in result


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_none_sql_returns_none(self):
        result = resolve_cloned_information_schema({}, None)
        assert result is None

    def test_empty_sql_returns_none(self):
        result = resolve_cloned_information_schema({}, "")
        assert result is None

    def test_malformed_json_falls_back_to_default(self):
        args = _make_workflow_args(strategy="custom", config="not valid json")
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_config_none_value_uses_default(self):
        args = _make_workflow_args(strategy="custom")
        args["control-config"] = None
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_cloned_schema_empty_string_uses_default(self):
        args = _make_workflow_args(
            strategy="custom", config='{"clonedInformationSchema": ""}'
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_default_prefix_constant(self):
        assert DEFAULT_INFORMATION_SCHEMA_PREFIX == "information_schema."

    def test_sql_without_placeholders_returned_unchanged(self):
        plain_sql = "SELECT 1"
        result = resolve_cloned_information_schema({}, plain_sql)
        assert result == "SELECT 1"

    def test_exclusion_empty_when_no_clone(self):
        """Default behavior produces no extra exclusion text."""
        result = resolve_cloned_information_schema({}, SAMPLE_SQL)
        assert result is not None
        # The exclusion placeholder should be replaced with empty string
        assert "'sys')" in result
        assert "'sys', " not in result

    def test_invalid_schema_name_with_quotes_rejected(self):
        """Schema names with SQL injection characters are rejected."""
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "test\'schema"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result
        assert "test" not in result

    def test_invalid_schema_name_with_spaces_rejected(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "bad schema"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_invalid_schema_name_with_semicolon_rejected(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "a; DROP TABLE"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "information_schema.TABLES" in result

    def test_valid_schema_name_with_underscores_and_numbers(self):
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "atlan_meta_v2"}',
        )
        result = resolve_cloned_information_schema(args, SAMPLE_SQL)
        assert result is not None
        assert "atlan_meta_v2.TABLES" in result


# ---------------------------------------------------------------------------
# Tests: actual SQL file resolution (PRD-MYSQL-CLONE-001)
# ---------------------------------------------------------------------------

SQL_DIR = Path(__file__).resolve().parents[2] / "app" / "sql"

SQL_FILES = [
    "extract_database.sql",
    "extract_schema.sql",
    "extract_table.sql",
    "extract_column.sql",
    "extract_procedure.sql",
    "filter_metadata.sql",
    "tables_check.sql",
]


def _read_sql(filename):
    return (SQL_DIR / filename).read_text()


class TestSQLFilePlaceholders:
    """Verify actual SQL files have correct placeholders and resolve properly."""

    @pytest.mark.parametrize("sql_file", SQL_FILES)
    def test_sql_file_has_cloned_placeholder(self, sql_file):
        """Every target SQL file must contain at least one {cloned_information_schema}."""
        sql = _read_sql(sql_file)
        assert (
            "{cloned_information_schema}" in sql
        ), f"{sql_file} missing {{cloned_information_schema}} placeholder"

    @pytest.mark.parametrize("sql_file", SQL_FILES)
    def test_sql_file_has_exclusion_placeholder(self, sql_file):
        """Every target SQL file must contain {cloned_schema_exclusion}."""
        sql = _read_sql(sql_file)
        assert (
            "{cloned_schema_exclusion}" in sql
        ), f"{sql_file} missing {{cloned_schema_exclusion}} placeholder"

    @pytest.mark.parametrize("sql_file", SQL_FILES)
    def test_sql_file_no_bare_information_schema_in_from(self, sql_file):
        """No bare information_schema. in FROM/JOIN clauses (comments OK)."""
        sql = _read_sql(sql_file)
        for i, line in enumerate(sql.splitlines(), 1):
            stripped = line.strip()
            # Skip comments
            if (
                stripped.startswith("--")
                or stripped.startswith("/*")
                or stripped.startswith("*")
            ):
                continue
            # Check for bare information_schema. that isn't inside a string literal
            if "information_schema." in stripped.lower():
                # It's OK if it's inside a NOT IN string literal like 'information_schema'
                # But NOT OK if it's a schema reference like information_schema.TABLES
                # Match information_schema.SOMETHING (a table reference, not a string)
                if re.search(r"(?<!')information_schema\.\w+", stripped, re.IGNORECASE):
                    pytest.fail(
                        f"{sql_file}:{i} has bare information_schema. reference:"
                        f" {stripped}"
                    )

    @pytest.mark.parametrize("sql_file", SQL_FILES)
    def test_default_resolution_produces_valid_sql(self, sql_file):
        """Default resolution (no config) produces information_schema. prefix."""
        sql = _read_sql(sql_file)
        resolved = resolve_cloned_information_schema({}, sql)
        assert resolved is not None
        assert "{cloned_information_schema}" not in resolved
        assert "{cloned_schema_exclusion}" not in resolved
        # Should contain real information_schema references
        assert "information_schema." in resolved.lower()

    @pytest.mark.parametrize("sql_file", SQL_FILES)
    def test_cloned_resolution_replaces_all_placeholders(self, sql_file):
        """Cloned resolution replaces all placeholders with custom schema."""
        sql = _read_sql(sql_file)
        args = _make_workflow_args(
            strategy="custom",
            config='{"clonedInformationSchema": "atlan_meta"}',
        )
        resolved = resolve_cloned_information_schema(args, sql)
        assert resolved is not None
        assert "{cloned_information_schema}" not in resolved
        assert "{cloned_schema_exclusion}" not in resolved
        assert "atlan_meta." in resolved
        assert ", 'atlan_meta'" in resolved
