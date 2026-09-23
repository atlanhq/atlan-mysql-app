"""The extract entrypoint receives the form's table exclusion (FND-2731).

The manifest sends ``exclude_table_regex`` ("Exclude regex for tables &
views"). It used to be dropped twice: ``run()`` took the SDK's bare
``ExtractionInput``, which does not declare it, and nothing mapped it onto the
``temp_table_regex`` field ``SqlApp`` actually builds its table filter from.
"""

from __future__ import annotations

import json

import pytest
from application_sdk.templates.contracts.sql_metadata import ExtractionTaskInput
from pydantic import ValidationError

from app.mysql import MySQLApp
from tests.manifest_args import extract_input_type, manifest_extract_args

_REGEX = ".*_TMP|.*_TEMP"

# ``{{connection}}`` renders as a JSON string, the shape AE substitutes.
_CONNECTION = json.dumps({
    "typeName": "Connection",
    "attributes": {"name": "example-connection", "qualifiedName": "default/mysql/1"},
})


def _validated(**overrides: object):
    args = manifest_extract_args(
        connection=_CONNECTION,
        extraction_method="direct",
        include_filter='{"^def$": [".*"]}',
        exclude_filter="{}",
        **overrides,
    )
    return extract_input_type().model_validate(args)


class TestManifestArgsSurviveValidation:
    def test_every_manifest_arg_is_declared_on_the_entrypoint_input(self):
        """Nothing the extract node sends is dropped as an unknown key.

        ``credential`` is the one exception: it is the connection form's raw
        credential widget, and the SDK resolves credentials from
        ``credential_guid`` / ``credential_ref`` instead.
        """
        fields = set(extract_input_type().model_fields)

        missing = set(manifest_extract_args()) - fields - {"credential"}

        assert not missing

    def test_exclude_table_regex_is_received_intact(self):
        model = _validated(exclude_table_regex=_REGEX)

        assert model.model_dump()["exclude_table_regex"] == _REGEX

    def test_exclude_table_regex_drives_temp_table_regex(self):
        """``temp_table_regex`` is what ``SqlApp`` substitutes into the query."""
        model = _validated(exclude_table_regex=_REGEX)

        assert model.temp_table_regex == _REGEX

    def test_the_form_placeholder_is_accepted(self):
        """A customer who copies the field's placeholder gets a valid run."""
        placeholder = ".*_TMP|.*_TEMP|TMP:*|TEMP:*"

        assert _validated(exclude_table_regex=placeholder).temp_table_regex == (
            placeholder
        )

    def test_an_empty_field_leaves_the_filter_off(self):
        assert _validated(exclude_table_regex="").temp_table_regex == ""

    def test_an_explicit_temp_table_regex_is_not_overwritten(self):
        model = _validated(exclude_table_regex=_REGEX, temp_table_regex="^scratch_")

        assert model.temp_table_regex == "^scratch_"

    def test_a_sql_injection_payload_is_rejected_at_the_boundary(self):
        """The value is spliced into a quoted SQL literal, so it must be checked.

        The mapping runs before field validation precisely so the SDK's
        ``temp_table_regex`` validators see it.
        """
        with pytest.raises(ValidationError):
            _validated(exclude_table_regex="x' OR '1'='1")


class TestExcludeTableRegexReachesTheExtractionSql:
    """SQL-rendering layer: manifest args → task input → rendered query."""

    @pytest.fixture
    def task_input(self) -> ExtractionTaskInput:
        model = _validated(exclude_table_regex=_REGEX)
        return MySQLApp().build_task_input(ExtractionTaskInput, model)

    @pytest.mark.parametrize("sql_attr", ["fetch_table_sql", "fetch_column_sql"])
    def test_table_and_column_queries_exclude_matching_tables(
        self, task_input: ExtractionTaskInput, sql_attr: str
    ):
        """Both queries filter on ``T.TABLE_NAME``.

        ``SqlApp`` injects only the *table* fragment, into both queries; the
        column query can take it because it LEFT JOINs ``information_schema.TABLES
        T``. Asserting the column render too pins that dependency.
        """
        app = MySQLApp()

        rendered = app._prepare_sql(getattr(app, sql_attr), task_input)

        assert f"AND T.TABLE_NAME NOT REGEXP '{_REGEX}'" in rendered
        assert "{temp_table_regex_sql}" not in rendered
