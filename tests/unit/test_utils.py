"""Unit tests for app.utils — clonedInformationSchema resolver."""

from __future__ import annotations

import pytest

from app.utils import (
    DEFAULT_INFORMATION_SCHEMA,
    extract_control_config,
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
