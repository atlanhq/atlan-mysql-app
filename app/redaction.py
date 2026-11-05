"""SQL-literal redaction behind the ``redact-sql-text`` toggle; no record is ever dropped."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from application_sdk.execution.heartbeat import run_in_thread
from application_sdk.observability.logger_adaptor import get_logger
from application_sdk.outputs import Metric, get_outputs
from query_redaction import RedactionConfig, RedactionStats, Status, redact_one

logger = get_logger(__name__)

#: SQL-bearing key in a raw table record; NULL for plain tables.
TABLE_SQL_PATHS: tuple[str, ...] = ("view_definition",)

#: SQL-bearing key in a raw procedure / function record.
PROCEDURE_SQL_PATHS: tuple[str, ...] = ("procedure_definition",)

#: Set by ``redaction_scope``, read by ``SQLClient.run_query``.
_ACTIVE: ContextVar[tuple[RedactionConfig, RedactionStats] | None] = ContextVar(
    "active_sql_redaction", default=None
)


def toggle_as_text(value: Any) -> Any:
    """Map a raw form bool to the generated contract's "true"/"false" string."""
    return str(value).lower() if isinstance(value, bool) else value


def toggle_on(redact_sql_text: Any) -> bool:
    """True when the toggle value means on."""
    return str(redact_sql_text).strip().lower() == "true"


def redaction_config(
    redact_sql_text: Any, columns: tuple[str, ...]
) -> RedactionConfig | None:
    """Config for ``columns``, or None when the toggle is off or no key holds SQL."""
    if not columns or not toggle_on(redact_sql_text):
        return None
    return RedactionConfig(columns=columns, dialect="mysql")


def redact_sql(
    record: dict[str, Any], config: RedactionConfig, stats: RedactionStats
) -> None:
    """Redact ``record``'s SQL keys in place; a dropped key keeps its original SQL."""
    for key in config.columns:
        sql = record.get(key)
        # The engine drops empty input.
        if not isinstance(sql, str) or not sql.strip():
            continue
        # redact_one's defaults differ from RedactionConfig's, so forward every knob.
        result = redact_one(
            sql,
            config.dialect,
            config.extra_allowlist,
            on_parse_failure=config.on_parse_failure,
            number_mode=config.number_mode,
            sentinel_value=config.sentinel_value,
            redact_comments=config.redact_comments,
            format_output=config.format_output,
        )
        stats.record(result)
        if result.status is not Status.REDACTED:
            logger.debug(
                "redaction NOT applied [%s]: status=%s reason=%s",
                key,
                result.status.name,
                result.reason,
            )
        if result.status is Status.DROPPED:
            continue
        record[key] = result.text


def redact_batch(
    records: list[dict[str, Any]], config: RedactionConfig, stats: RedactionStats
) -> None:
    """Redact ``records`` in place; every record is kept."""
    for record in records:
        redact_sql(record, config, stats)


@contextmanager
def redaction_scope(config: RedactionConfig) -> Iterator[RedactionStats]:
    """Make ``config`` active for SQL queries run in this context; yields its stats."""
    stats = RedactionStats()
    token = _ACTIVE.set((config, stats))
    try:
        yield stats
    finally:
        _ACTIVE.reset(token)


def redacting(
    batches: AsyncGenerator[list[dict[str, Any]], None],
) -> AsyncGenerator[list[dict[str, Any]], None]:
    """``batches`` as is, or redacted per batch when a scope is active."""
    active = _ACTIVE.get()
    return batches if active is None else _redact_batches(batches, *active)


async def _redact_batches(
    batches: AsyncIterator[list[dict[str, Any]]],
    config: RedactionConfig,
    stats: RedactionStats,
) -> AsyncGenerator[list[dict[str, Any]], None]:
    async for batch in batches:
        # CPU-bound parse: off the loop so the heartbeat keeps running.
        await run_in_thread(redact_batch, batch, config, stats)
        yield batch


def emit_redaction_metrics(counts: dict[str, int]) -> None:
    """Emit the ``qi-redaction-*`` counts as workflow metrics."""
    outputs = get_outputs()
    for name, value in counts.items():
        outputs.add_metric(Metric(name=name, value=value))
