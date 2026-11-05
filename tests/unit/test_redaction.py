"""SQL-text redaction: gate, toggle plumbing, per-record helpers and the extract seam."""

from __future__ import annotations

import asyncio
import json
import typing
from pathlib import Path
from unittest.mock import patch

import pytest
from application_sdk.app.task import get_task_metadata
from application_sdk.clients.sql import AsyncBaseSQLClient
from application_sdk.templates.contracts.sql_metadata import (
    ExtractionInput,
    ExtractionTaskInput,
    ExtractionTaskOutput,
)
from application_sdk.templates.sql_app import SqlApp
from query_redaction import RedactionResult, RedactionStats, Status

import app.redaction as redaction
from app.client import SQLClient
from app.mysql import MySQLApp, MySQLExtractionInput, MySQLExtractionTaskInput
from app.redaction import (
    PROCEDURE_SQL_PATHS,
    TABLE_SQL_PATHS,
    redact_batch,
    redact_sql,
    redaction_config,
    redaction_scope,
)

_GENERATED = Path(__file__).resolve().parents[2] / "app" / "generated"
_VIEW_SQL = "SELECT id FROM orders WHERE customer = 'Acme' AND total > 100"


def _config(columns=TABLE_SQL_PATHS):
    cfg = redaction_config("true", columns)
    assert cfg is not None
    return cfg


class TestRedactionGate:
    @pytest.mark.parametrize("flag", ["false", "False", "", None, False, "no"])
    def test_off_values_return_no_config(self, flag):
        assert redaction_config(flag, TABLE_SQL_PATHS) is None

    @pytest.mark.parametrize("flag", ["true", "TRUE", " true ", True])
    def test_on_values_return_a_mysql_config(self, flag):
        cfg = redaction_config(flag, PROCEDURE_SQL_PATHS)
        assert cfg is not None
        assert cfg.dialect == "mysql"
        assert cfg.columns == PROCEDURE_SQL_PATHS

    def test_no_sql_keys_means_no_config(self):
        assert redaction_config("true", ()) is None


class TestTogglePlumbing:
    """The form sends a bool, and the SDK drops undeclared keys."""

    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({}, "false"),
            ({"redact_sql_text": False}, "false"),
            ({"redact_sql_text": True}, "true"),
            ({"redact_sql_text": "true"}, "true"),
        ],
    )
    def test_raw_form_values_validate(self, payload, expected):
        assert MySQLExtractionInput.model_validate(payload).redact_sql_text == expected

    def test_run_is_annotated_with_the_toggle_input(self):
        hints = typing.get_type_hints(MySQLApp.run)
        assert hints["input"] is MySQLExtractionInput

    @pytest.mark.parametrize("name", ["extract_tables", "extract_procedures"])
    def test_sql_bearing_extracts_stay_tasks_with_the_sdk_settings(self, name):
        ours = get_task_metadata(getattr(MySQLApp, name))
        sdk = get_task_metadata(getattr(SqlApp, name))
        assert ours is not None and sdk is not None
        assert ours.input_type is MySQLExtractionTaskInput
        assert (ours.name, ours.output_type) == (sdk.name, sdk.output_type)
        assert (
            ours.timeout_seconds,
            ours.heartbeat_timeout_seconds,
            ours.auto_heartbeat_seconds,
            ours.retry_max_attempts,
        ) == (
            sdk.timeout_seconds,
            sdk.heartbeat_timeout_seconds,
            sdk.auto_heartbeat_seconds,
            sdk.retry_max_attempts,
        )

    def test_toggle_off_task_input_is_the_sdk_one(self):
        src = MySQLExtractionInput(redact_sql_text="false")
        task_input = MySQLApp.build_task_input(ExtractionTaskInput, src)
        assert type(task_input) is ExtractionTaskInput
        assert task_input == SqlApp.build_task_input(ExtractionTaskInput, src)

    def test_toggle_on_task_input_carries_it(self):
        src = MySQLExtractionInput(redact_sql_text=True, temp_table_regex="tmp_.*")
        task_input = MySQLApp.build_task_input(ExtractionTaskInput, src)
        assert isinstance(task_input, MySQLExtractionTaskInput)
        assert task_input.redact_sql_text == "true"
        assert task_input.temp_table_regex == "tmp_.*"

    def test_plain_sdk_input_builds_without_the_toggle(self):
        task_input = MySQLApp.build_task_input(ExtractionTaskInput, ExtractionInput())
        assert type(task_input) is ExtractionTaskInput


class TestRedactSql:
    @staticmethod
    def _redact(sql, key="view_definition"):
        record = {key: sql}
        redact_sql(record, _config((key,)), RedactionStats())
        return record[key]

    def test_literals_are_replaced_and_structure_kept(self):
        out = self._redact(_VIEW_SQL)
        assert "Acme" not in out and "100" not in out
        assert out.startswith("/* redacted: true")
        assert "orders" in out and "customer" in out

    def test_routine_body_is_redacted(self):
        out = self._redact(
            "SELECT name FROM users WHERE email = 'a@example.com'",
            key="procedure_definition",
        )
        assert "a@example.com" not in out
        assert out.startswith("/* redacted: true")

    def test_unparseable_sql_passes_through_under_a_header(self):
        out = self._redact("SELEC 'Acme' FRM")
        assert out.startswith("/* redacted: false")
        assert "SELEC 'Acme' FRM" in out

    @pytest.mark.parametrize("sql", ["", "   ", None])
    def test_blank_sql_is_left_alone(self, sql):
        stats = RedactionStats()
        record = {"view_definition": sql}
        redact_sql(record, _config(), stats)
        assert record == {"view_definition": sql}
        assert stats.total == 0

    def test_dropped_sql_keeps_the_record_and_its_original_sql(self, monkeypatch):
        monkeypatch.setattr(
            redaction,
            "redact_one",
            lambda sql, *_a, **_k: RedactionResult(
                status=Status.DROPPED if "Initech" in sql else Status.REDACTED,
                text=None if "Initech" in sql else "redacted",
            ),
        )
        records = [
            {"table_name": "kept", "view_definition": "SELECT 1"},
            {"table_name": "dropped", "view_definition": "SELECT 'Initech'"},
        ]
        redact_batch(records, _config(), RedactionStats())
        assert records == [
            {"table_name": "kept", "view_definition": "redacted"},
            {"table_name": "dropped", "view_definition": "SELECT 'Initech'"},
        ]


def _sdk_batches(*batches):
    async def run_query(self, query, batch_size=100000, params=None):
        for batch in batches:
            yield batch

    return patch.object(AsyncBaseSQLClient, "run_query", run_query)


async def _collect(gen):
    return [batch async for batch in gen]


class TestClientSeam:
    def test_no_scope_returns_the_sdk_generator_untouched(self):
        rows = [{"table_name": "v", "view_definition": _VIEW_SQL}]
        with _sdk_batches(rows):
            gen = SQLClient().run_query("SELECT 1")
            assert gen.__qualname__.endswith("run_query")
            assert asyncio.run(_collect(gen)) == [
                [{"table_name": "v", "view_definition": _VIEW_SQL}]
            ]

    def test_scope_redacts_every_batch_in_place(self):
        first = [{"table_name": "v", "view_definition": _VIEW_SQL}]
        second = [{"table_name": "t", "view_definition": None}]

        async def run():
            with redaction_scope(_config()) as stats:
                out = await _collect(SQLClient().run_query("SELECT 1"))
            return out, stats

        with _sdk_batches(first, second):
            out, stats = asyncio.run(run())
        assert out[0] is first and out[1] is second
        assert "Acme" not in first[0]["view_definition"]
        assert second == [{"table_name": "t", "view_definition": None}]
        assert stats.as_dict()["qi-redaction-redacted"] == 1


class TestExtractOverride:
    @staticmethod
    def _run(method, toggle):
        seen = {}

        async def sdk_extract(self, input):
            seen["active"] = redaction._ACTIVE.get()
            return ExtractionTaskOutput(typename="table", total_record_count=1)

        app = MySQLApp.__new__(MySQLApp)
        with (
            patch.object(SqlApp, method, sdk_extract),
            patch("app.mysql.emit_redaction_metrics") as emit,
        ):
            result = asyncio.run(
                getattr(app, method)(MySQLExtractionTaskInput(redact_sql_text=toggle))
            )
        return result, seen["active"], emit

    @pytest.mark.parametrize(
        "method, columns",
        [
            ("extract_tables", TABLE_SQL_PATHS),
            ("extract_procedures", PROCEDURE_SQL_PATHS),
        ],
    )
    def test_toggle_on_opens_a_scope_and_emits_metrics_once(self, method, columns):
        result, active, emit = self._run(method, "true")
        assert result.total_record_count == 1
        assert active is not None and active[0].columns == columns
        emit.assert_called_once()
        assert redaction._ACTIVE.get() is None

    @pytest.mark.parametrize("method", ["extract_tables", "extract_procedures"])
    def test_toggle_off_runs_the_sdk_extract_without_a_scope(self, method):
        _, active, emit = self._run(method, "false")
        assert active is None
        emit.assert_not_called()


class TestGeneratedContract:
    def test_manifest_wires_the_toggle_into_extract(self):
        manifest = json.loads((_GENERATED / "manifest.json").read_text())
        args = manifest["dag"]["extract"]["inputs"]["args"]
        assert args["redact_sql_text"] == "{{redact-sql-text}}"

    def test_toggle_is_visible_for_direct_and_agent_runs(self):
        form = json.loads((_GENERATED / "mysql.json").read_text())["config"]
        prop = form["properties"]["redact-sql-text"]
        assert prop["default"] is False
        assert prop["ui"]["hidden"] is False
        assert "conditions" not in prop
        assert "redact-sql-text" not in json.dumps(form.get("anyOf", []))
