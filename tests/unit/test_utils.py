"""Unit tests for app.utils — clonedInformationSchema resolver."""

from __future__ import annotations

import pytest

from app.utils import (
    DEFAULT_EXCLUDED_SCHEMAS,
    DEFAULT_INFORMATION_SCHEMA,
    extract_control_config,
    resolve_excluded_schemas,
    resolve_information_schema,
)

# ── resolve_information_schema ────────────────────────────────────────


class TestResolveInformationSchemaDefaults:
    """Without control-config, behavior must be byte-identical to today."""

    def test_no_control_config_resolves_to_information_schema(self):
        sql = "SELECT * FROM {information_schema}.SCHEMATA"
        assert (
            resolve_information_schema(sql, None)
            == "SELECT * FROM information_schema.SCHEMATA"
        )

    def test_empty_dict_resolves_to_information_schema(self):
        sql = "SELECT * FROM {information_schema}.TABLES"
        assert (
            resolve_information_schema(sql, {})
            == "SELECT * FROM information_schema.TABLES"
        )

    def test_dict_without_cloned_key_resolves_to_information_schema(self):
        sql = "SELECT * FROM {information_schema}.COLUMNS"
        assert (
            resolve_information_schema(sql, {"otherKey": "value"})
            == "SELECT * FROM information_schema.COLUMNS"
        )

    def test_template_without_placeholder_unchanged(self):
        sql = "SELECT 1"
        assert resolve_information_schema(sql, None) == "SELECT 1"

    def test_empty_template_returns_empty(self):
        assert resolve_information_schema("", None) == ""

    def test_default_constant_unchanged(self):
        assert DEFAULT_INFORMATION_SCHEMA == "information_schema"


class TestResolveInformationSchemaWithMirror:
    """With clonedInformationSchema set, placeholder resolves to the mirror."""

    def test_mirror_schema_substituted(self):
        sql = "SELECT * FROM {information_schema}.SCHEMATA"
        result = resolve_information_schema(
            sql, {"clonedInformationSchema": "atlan_meta"}
        )
        assert result == "SELECT * FROM atlan_meta.SCHEMATA"

    def test_multiple_placeholders_all_substituted(self):
        sql = (
            "SELECT C.COLUMN_NAME FROM {information_schema}.COLUMNS C "
            "JOIN {information_schema}.TABLES T ON C.TABLE_NAME = T.TABLE_NAME "
            "WHERE T.TABLE_SCHEMA NOT IN ('mysql', 'information_schema')"
        )
        result = resolve_information_schema(
            sql, {"clonedInformationSchema": "atlan_meta"}
        )
        # All {information_schema} placeholders are replaced
        assert "{information_schema}" not in result
        assert result.count("atlan_meta.") == 2
        # The literal string in the NOT IN clause is untouched
        assert "'information_schema'" in result

    def test_mirror_schema_with_underscore(self):
        sql = "SELECT * FROM {information_schema}.t"
        result = resolve_information_schema(
            sql, {"clonedInformationSchema": "my_metadata_schema"}
        )
        assert result == "SELECT * FROM my_metadata_schema.t"

    def test_mirror_schema_starting_with_underscore(self):
        sql = "FROM {information_schema}.x"
        assert (
            resolve_information_schema(sql, {"clonedInformationSchema": "_private"})
            == "FROM _private.x"
        )

    def test_whitespace_stripped(self):
        sql = "FROM {information_schema}.x"
        assert (
            resolve_information_schema(
                sql, {"clonedInformationSchema": "  atlan_meta  "}
            )
            == "FROM atlan_meta.x"
        )


class TestResolveInformationSchemaValidation:
    """Customer-supplied schema names must pass identifier validation."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "atlan-meta",  # hyphen not allowed
            "atlan meta",  # space not allowed
            "atlan.meta",  # dot not allowed
            "1atlan",  # cannot start with digit
            "atlan;DROP TABLE users;--",  # SQL-injection attempt
            "atlan`meta",  # backtick
            "atlan'meta",  # quote
            "x" * 65,  # too long (>64 chars)
            "",  # empty
            "   ",  # whitespace-only
        ],
    )
    def test_invalid_identifier_raises(self, bad_name):
        sql = "FROM {information_schema}.x"
        with pytest.raises(ValueError, match="clonedInformationSchema"):
            resolve_information_schema(sql, {"clonedInformationSchema": bad_name})

    @pytest.mark.parametrize(
        "non_string",
        [
            123,
            12.5,
            ["atlan_meta"],
            {"name": "atlan_meta"},
            True,
        ],
    )
    def test_non_string_value_raises(self, non_string):
        sql = "FROM {information_schema}.x"
        with pytest.raises(ValueError, match="clonedInformationSchema"):
            resolve_information_schema(sql, {"clonedInformationSchema": non_string})

    def test_none_value_falls_back_to_default(self):
        """clonedInformationSchema: null in JSON → behaves like absent."""
        sql = "FROM {information_schema}.x"
        assert (
            resolve_information_schema(sql, {"clonedInformationSchema": None})
            == "FROM information_schema.x"
        )

    def test_max_length_identifier_accepted(self):
        """64-char identifier is the MySQL limit — must be allowed."""
        name = "a" + ("b" * 63)
        assert len(name) == 64
        sql = "FROM {information_schema}.x"
        assert (
            resolve_information_schema(sql, {"clonedInformationSchema": name})
            == f"FROM {name}.x"
        )


# ── extract_control_config ────────────────────────────────────────────


class TestExtractControlConfigDict:
    """When source is a plain dict (common in workflow_args / AE payloads)."""

    def test_no_strategy_returns_empty(self):
        assert extract_control_config({"control-config": {"x": 1}}) == {}

    def test_default_strategy_returns_empty(self):
        assert (
            extract_control_config({
                "control-config-strategy": "default",
                "control-config": {"x": 1},
            })
            == {}
        )

    def test_custom_strategy_with_dict(self):
        assert extract_control_config({
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        }) == {"clonedInformationSchema": "atlan_meta"}

    def test_custom_strategy_with_json_string(self):
        assert extract_control_config({
            "control-config-strategy": "custom",
            "control-config": '{"clonedInformationSchema": "atlan_meta"}',
        }) == {"clonedInformationSchema": "atlan_meta"}

    def test_custom_strategy_with_malformed_json_returns_empty(self):
        """Malformed JSON must fail soft, not crash."""
        assert (
            extract_control_config({
                "control-config-strategy": "custom",
                "control-config": "not valid json",
            })
            == {}
        )

    def test_custom_strategy_with_empty_config(self):
        assert (
            extract_control_config({
                "control-config-strategy": "custom",
                "control-config": {},
            })
            == {}
        )

    def test_underscore_key_form(self):
        """Pydantic-normalized form uses underscores instead of hyphens."""
        assert extract_control_config({
            "control_config_strategy": "custom",
            "control_config": {"clonedInformationSchema": "atlan_meta"},
        }) == {"clonedInformationSchema": "atlan_meta"}

    def test_case_insensitive_custom(self):
        """Strategy comparison should be case-insensitive — UI may emit Custom."""
        assert extract_control_config({
            "control-config-strategy": "Custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        }) == {"clonedInformationSchema": "atlan_meta"}


class TestExtractControlConfigObject:
    """When source is a pydantic-like object (handler-side BaseConnectionConfig)."""

    def test_attribute_access(self):
        class Obj:
            control_config_strategy = "custom"
            control_config = {"clonedInformationSchema": "mirror"}

        assert extract_control_config(Obj()) == {"clonedInformationSchema": "mirror"}

    def test_missing_attributes_returns_empty(self):
        class Obj:
            pass

        assert extract_control_config(Obj()) == {}

    def test_none_source_returns_empty(self):
        assert extract_control_config(None) == {}


class TestEndToEnd:
    """Integration of extract_control_config + resolve_information_schema."""

    def test_full_pipeline_with_custom(self):
        source = {
            "control-config-strategy": "custom",
            "control-config": '{"clonedInformationSchema": "atlan_meta"}',
        }
        sql = "SELECT * FROM {information_schema}.SCHEMATA"
        config = extract_control_config(source)
        assert (
            resolve_information_schema(sql, config)
            == "SELECT * FROM atlan_meta.SCHEMATA"
        )

    def test_full_pipeline_with_default(self):
        source = {"control-config-strategy": "default"}
        sql = "SELECT * FROM {information_schema}.SCHEMATA"
        config = extract_control_config(source)
        assert (
            resolve_information_schema(sql, config)
            == "SELECT * FROM information_schema.SCHEMATA"
        )

    def test_combined_resolvers_apply_same_mirror(self):
        """Both placeholders must read the same control-config and stay in sync."""
        source = {
            "control-config-strategy": "custom",
            "control-config": '{"clonedInformationSchema": "atlan_meta"}',
        }
        sql = (
            "SELECT * FROM {information_schema}.TABLES T "
            "WHERE T.TABLE_SCHEMA NOT IN ({excluded_schemas})"
        )
        config = extract_control_config(source)
        prepared = resolve_information_schema(sql, config)
        prepared = resolve_excluded_schemas(prepared, config)
        # information_schema → mirror
        assert "atlan_meta.TABLES" in prepared
        # mirror name appended to the exclusion list (so the mirror's own
        # pass-through views aren't crawled as user assets)
        assert (
            "NOT IN ("
            "'mysql', 'performance_schema', 'information_schema', 'sys', "
            "'atlan_meta')"
        ) in prepared
        # No unresolved placeholders left
        assert "{information_schema}" not in prepared
        assert "{excluded_schemas}" not in prepared


# ── resolve_excluded_schemas ──────────────────────────────────────────


class TestResolveExcludedSchemasDefaults:
    """Without a mirror configured, the rendered list equals the original literal."""

    def test_default_constant_matches_legacy_sql_literal(self):
        """Tuple ordering matters — every legacy SQL file used this exact set."""
        assert DEFAULT_EXCLUDED_SCHEMAS == (
            "mysql",
            "performance_schema",
            "information_schema",
            "sys",
        )

    def test_no_control_config_renders_default_list(self):
        sql = "WHERE S.SCHEMA_NAME NOT IN ({excluded_schemas})"
        assert resolve_excluded_schemas(sql, None) == (
            "WHERE S.SCHEMA_NAME NOT IN "
            "('mysql', 'performance_schema', 'information_schema', 'sys')"
        )

    def test_empty_dict_renders_default_list(self):
        sql = "NOT IN ({excluded_schemas})"
        assert resolve_excluded_schemas(sql, {}) == (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')"
        )

    def test_dict_without_cloned_key_renders_default_list(self):
        sql = "NOT IN ({excluded_schemas})"
        assert resolve_excluded_schemas(sql, {"otherKey": "value"}) == (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')"
        )

    def test_template_without_placeholder_unchanged(self):
        assert resolve_excluded_schemas("SELECT 1", None) == "SELECT 1"

    def test_empty_template_returns_empty(self):
        assert resolve_excluded_schemas("", None) == ""


class TestResolveExcludedSchemasWithMirror:
    """With clonedInformationSchema set, the mirror is appended to the list."""

    def test_mirror_name_appended(self):
        sql = "NOT IN ({excluded_schemas})"
        assert resolve_excluded_schemas(
            sql, {"clonedInformationSchema": "atlan_meta"}
        ) == (
            "NOT IN ("
            "'mysql', 'performance_schema', 'information_schema', 'sys', "
            "'atlan_meta')"
        )

    def test_mirror_already_in_default_list_not_duplicated(self):
        """Defensive: if a customer configures a system schema name, list once."""
        sql = "NOT IN ({excluded_schemas})"
        result = resolve_excluded_schemas(sql, {"clonedInformationSchema": "mysql"})
        assert result.count("'mysql'") == 1

    def test_multiple_placeholders_all_substituted(self):
        sql = "WHERE S NOT IN ({excluded_schemas}) AND T NOT IN ({excluded_schemas})"
        result = resolve_excluded_schemas(
            sql, {"clonedInformationSchema": "atlan_meta"}
        )
        assert "{excluded_schemas}" not in result
        assert result.count("'atlan_meta'") == 2

    def test_whitespace_stripped_before_appending(self):
        sql = "NOT IN ({excluded_schemas})"
        result = resolve_excluded_schemas(
            sql, {"clonedInformationSchema": "  atlan_meta  "}
        )
        assert "'atlan_meta'" in result
        assert "'  atlan_meta  '" not in result


class TestResolveExcludedSchemasValidation:
    """Identifier validation contract is identical to resolve_information_schema."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "atlan-meta",  # hyphen not allowed
            "atlan meta",  # space not allowed
            "atlan.meta",  # dot not allowed
            "1atlan",  # cannot start with digit
            "atlan;DROP TABLE users;--",  # SQL-injection attempt
            "atlan`meta",  # backtick
            "atlan'meta",  # quote
            "x" * 65,  # too long (>64 chars)
            "",  # empty
            "   ",  # whitespace-only
        ],
    )
    def test_invalid_identifier_raises(self, bad_name):
        sql = "NOT IN ({excluded_schemas})"
        with pytest.raises(ValueError, match="clonedInformationSchema"):
            resolve_excluded_schemas(sql, {"clonedInformationSchema": bad_name})

    @pytest.mark.parametrize(
        "non_string",
        [123, 12.5, ["atlan_meta"], {"name": "atlan_meta"}, True],
    )
    def test_non_string_value_raises(self, non_string):
        sql = "NOT IN ({excluded_schemas})"
        with pytest.raises(ValueError, match="clonedInformationSchema"):
            resolve_excluded_schemas(sql, {"clonedInformationSchema": non_string})

    def test_none_value_falls_back_to_default(self):
        sql = "NOT IN ({excluded_schemas})"
        assert resolve_excluded_schemas(sql, {"clonedInformationSchema": None}) == (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')"
        )

    def test_max_length_identifier_accepted(self):
        """64-char identifier is the MySQL limit — must be allowed."""
        name = "a" + ("b" * 63)
        assert len(name) == 64
        sql = "NOT IN ({excluded_schemas})"
        result = resolve_excluded_schemas(sql, {"clonedInformationSchema": name})
        assert f"'{name}'" in result
