"""Registered preflight behaviour scenarios (conformance F016).

Every test here drives the **real** ``MySQLAppHandler.preflight_check`` and
validates its output with ``assert_preflight_result``. Nothing in the handler,
its error classification (``app.failures.transient_failure`` /
``_mysql_errno``), its short-circuit or its verdict aggregation is mocked.

Source adapter — where the fake stops
-------------------------------------
``atlan-openapi-app`` fakes its source at the HTTP transport (respx) so the
real client runs. The MySQL equivalent is two seams, because one of them needs
a live ``AsyncEngine`` that no stub can supply:

* ``sqlalchemy.ext.asyncio.create_async_engine`` returns a synthetic engine.
  The app's **real** ``SQLClient.load`` still runs end to end — SSL context,
  the SDR ``basic.username`` / ``basic.password`` flattening, the
  caching_sha2_password tenacity retry, required-field validation, connection
  string construction, and the SDK's own ``SqlClientAuthFailedError`` wrapping
  of whatever the connection raises. Auth failures are injected at
  ``engine.connect()``, so the app classifies a real driver exception.
* ``SQLClient.get_results`` is stubbed, because the SDK's read path
  (``_execute_async_read_operation``) requires an ``isinstance`` check against
  a real ``AsyncEngine``. Query failures are injected in the shape the SDK
  delivers them: ``SqlPandasResultError(cause=<driver error>, retryable=True)``.

``SQLClient.close`` is left real, so engine disposal is independent teardown
evidence rather than a recorded mock call.

Scenario mapping decisions
--------------------------
The guide's matrix is written for a multi-resource source. Two names needed a
decision, recorded here rather than in a commit message:

* ``mixed_resources`` — this connector probes one connection per invocation,
  so its distinct resources are distinct sources. The scenario runs two
  synthetic sources (one fully readable, one whose table listing is denied)
  and asserts each verdict is decided only by its own rows.
* ``extraction_fallback`` — this app has no in-app preflight retry or
  fallback. What the gate's continue-on-advisory-failure actually rests on is
  probe/extraction parity: ``tables_check.sql`` and ``extract_table.sql`` read
  the same ``information_schema.TABLES`` through the same client, so the
  scenario asserts the same injected permission failure reaches both paths and
  that a READY verdict never claims a capability extraction lacks.

Probe roles for this handler, declared once here rather than inferred from
names (the guide forbids guessing them):

* ``auth`` — mandatory. A definitive auth failure blocks: NOT_READY.
* ``connectivity`` — advisory. It may fail without changing the verdict.

Three scenarios needed a handler-contract change before they could be written
truthfully, and the handler now carries it:

* ``recoverable_transient`` — a blip used to be reported as READY carrying a
  failed *mandatory* auth row, which ``assert_preflight_result`` rejects and
  which is a green light nothing verified. The handler now raises the typed
  retryable leaf instead, so the gate asks again.
* ``hung_probe`` / ``budget_retry`` — the handler ignored
  ``PreflightInput.timeout_seconds`` entirely, so nothing bounded a probe by
  the gate's remaining budget. It now derives a deadline from it
  (``app.handler._probe_deadline`` / ``_connect_timeout``).
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pymysql.err as pymysql_err
import pytest
import sqlalchemy.exc as sqlalchemy_exc
import sqlalchemy.ext.asyncio as sqlalchemy_async
from application_sdk.clients.sql_errors import SqlPandasResultError
from loguru import logger as loguru_logger
from application_sdk.handler import HandlerCredential, PreflightInput
from conformance.preflight_testing import (
    assert_preflight_result,
    assert_probe_lifetime,
)

from app.client import SQLClient
from app.failures import PreflightProbeTimeoutError, SourceRestartingError
from app.handler import _TABLES_CHECK_SQL, _TEST_AUTH_SQL, MySQLAppHandler

# Synthetic only — never a real credential. Used to prove the password never
# reaches the gate's output or the logs, on the path that carries a driver
# message (SQLAlchemy embeds the connection URL in its error text).
SYNTHETIC_PASSWORD = "SyntheticMySqlPw0000"

MANDATORY = ("auth",)
OBSERVED = {"auth", "connectivity"}

# MySQL server error numbers used by the scenarios. 1045/1142 are definitive
# customer-fixable facts; app.failures._SERVER_BLIP_ERRNOS holds the retryable
# ones, which only the deferred recoverable_transient scenario needs.
ERRNO_ACCESS_DENIED = 1045
ERRNO_NO_SELECT_GRANT = 1142
ERRNO_CONNECTION_LOST = 2013  # app.failures._SERVER_BLIP_ERRNOS


def _connect_timeouts(source: SyntheticMySQL) -> list[int]:
    """The connect deadline the app put on each connection it built."""
    return [
        int(parse_qs(urlparse(url).query)["connect_timeout"][0]) for url in source.urls
    ]


def _driver_error(errno: int, text: str) -> Exception:
    """A driver error in the shape SQLAlchemy delivers it to the app."""
    return sqlalchemy_exc.OperationalError(
        "SELECT 1", {}, pymysql_err.OperationalError(errno, text)
    )


def _access_denied() -> Exception:
    return _driver_error(
        ERRNO_ACCESS_DENIED,
        "Access denied for user 'atlan_reader'@'10.0.0.1' (using password: YES)",
    )


def _grant_denied() -> SqlPandasResultError:
    """What the SDK's get_results raises when the listing query is refused."""
    cause = _driver_error(
        ERRNO_NO_SELECT_GRANT,
        "SELECT command denied to user 'atlan_reader'@'10.0.0.1' for table 'TABLES'",
    )
    try:
        raise SqlPandasResultError(cause=cause, retryable=True) from cause
    except SqlPandasResultError as raised:
        return raised


# =============================================================================
# The source adapter
# =============================================================================


class _SyntheticConnection:
    def __init__(self, source: SyntheticMySQL) -> None:
        self._source = source

    async def __aenter__(self) -> _SyntheticConnection:
        self._source.connects += 1
        if self._source.connect_error is not None:
            raise self._source.connect_error
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _SyntheticEngine:
    """Stands in for an AsyncEngine; records the URL the app built for it."""

    def __init__(self, source: SyntheticMySQL, url: str, **kwargs: Any) -> None:
        self._source = source
        self.url = url
        self.kwargs = kwargs
        # install_tolerant_text_decoder_hook() attaches a DBAPI event to this;
        # a plain object is enough for the hook to bind to and never fire.
        self.sync_engine = type("SyncEngine", (), {})()

    def connect(self) -> _SyntheticConnection:
        return _SyntheticConnection(self._source)

    async def dispose(self) -> None:
        self._source.disposed += 1


class SyntheticMySQL:
    """An app-owned synthetic MySQL source.

    Failures are injected where the real source produces them: at the
    connection for auth, and at the read for the table listing.
    """

    def __init__(self) -> None:
        self.connect_error: BaseException | None = None
        self.responses: dict[str, Any] = {}
        self.urls: list[str] = []
        self.queries: list[str] = []
        self.connects = 0
        self.disposed = 0

    # -- configuration ----------------------------------------------------
    def answer(self, query: str, value: Any) -> None:
        """Answer `query` with a DataFrame, an exception, or a coroutine fn."""
        self.responses[query] = value

    def deny_listing(self) -> None:
        self.answer(_TABLES_CHECK_SQL, _grant_denied())

    # -- seams ------------------------------------------------------------
    def _engine(self, url: str, **kwargs: Any) -> _SyntheticEngine:
        self.urls.append(str(url))
        return _SyntheticEngine(self, str(url), **kwargs)

    async def _get_results(self, query: str) -> pd.DataFrame:
        self.queries.append(query)
        value = self.responses.get(query)
        if value is None:
            return pd.DataFrame({"count": [42]})
        if callable(value):
            return await value()
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> SyntheticMySQL:
    adapter = SyntheticMySQL()

    monkeypatch.setattr(
        sqlalchemy_async,
        "create_async_engine",
        lambda url, **kwargs: adapter._engine(url, **kwargs),
    )

    async def _get_results(self: SQLClient, query: str) -> pd.DataFrame:
        return await adapter._get_results(query)

    monkeypatch.setattr(SQLClient, "get_results", _get_results)
    return adapter


@pytest.fixture
def captured_logs() -> Any:
    """Everything the handler and the SDK log during a scenario.

    The SDK logs through loguru, which pytest's caplog does not see, so the
    sink is attached directly.
    """
    buffer = io.StringIO()
    sink = loguru_logger.add(buffer, level="DEBUG")
    try:
        yield buffer
    finally:
        loguru_logger.remove(sink)


def _credentials(**overrides: Any) -> list[HandlerCredential]:
    values: dict[str, Any] = {
        "host": "mysql.internal.example",
        "port": "3306",
        "username": "atlan_reader",
        "password": SYNTHETIC_PASSWORD,
        "authType": "basic",
    }
    values.update(overrides)
    return [
        HandlerCredential(key=key, value=value)
        for key, value in values.items()
        if value is not None
    ]


async def _run(budget: int = 60, **overrides: Any) -> Any:
    return await MySQLAppHandler().preflight_check(
        PreflightInput(credentials=_credentials(**overrides), timeout_seconds=budget)
    )


# =============================================================================
# Healthy and failure verdicts
# =============================================================================


@pytest.mark.preflight_conformance(rule="F016", scenario="healthy")
async def test_readable_source_is_ready(source: SyntheticMySQL) -> None:
    """A source that authenticates and lists tables: both rows pass, READY."""
    result = await _run()

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert all(check.passed for check in result.checks)
    assert source.queries == [_TEST_AUTH_SQL, _TABLES_CHECK_SQL]
    # Every engine the app built was disposed.
    assert source.disposed == len(source.urls) == 1


@pytest.mark.preflight_conformance(rule="F016", scenario="mandatory_failure")
async def test_access_denied_blocks_and_short_circuits(
    source: SyntheticMySQL,
) -> None:
    """A definitive auth refusal blocks the run with typed attribution, and the
    advisory listing behind it never runs."""
    source.connect_error = _access_denied()

    result = await _run()

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="not_ready",
        mandatory_order=MANDATORY,
        expected_errors={
            "auth": {
                "category": "AUTH",
                "code": "AUTH_MYSQL_PREFLIGHT",
                "retryable": False,
                "audience": "USER",
            }
        },
    )
    assert {check.name for check in result.checks} == {"auth"}
    assert source.queries == []
    # The app's caching_sha2_password retry made several attempts; each one
    # disposed the engine it built rather than leaking it.
    assert source.disposed == len(source.urls) > 1


@pytest.mark.preflight_conformance(rule="F016", scenario="advisory_failure")
async def test_missing_select_grant_fails_advisory_without_blocking(
    source: SyntheticMySQL,
) -> None:
    """A connection that authenticates but cannot list tables is the classic
    half-configured source. The advisory row fails with a typed, actionable
    error and the verdict stays READY — extraction can still proceed."""
    source.deny_listing()

    result = await _run()

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
        expected_errors={
            "connectivity": {
                "category": "PERMISSION",
                "code": "PERMISSION_MYSQL_TABLE_LISTING",
                "retryable": False,
                "audience": "USER",
            }
        },
    )
    auth = next(check for check in result.checks if check.name == "auth")
    connectivity = next(
        check for check in result.checks if check.name == "connectivity"
    )
    assert auth.passed is True
    assert connectivity.passed is False
    assert connectivity.error is not None
    assert connectivity.error.suggested_action


@pytest.mark.preflight_conformance(rule="F016", scenario="persistent_failure")
async def test_access_denied_is_a_stable_verdict_across_attempts(
    source: SyntheticMySQL,
) -> None:
    """An access refusal is a stable, customer-fixable fact, so it stays a
    verdict rather than a transient — and it does not clear with retries.
    Exhaustion for this connector is the same NOT_READY twice."""
    source.connect_error = _access_denied()

    for _ in range(2):
        result = await _run()
        assert_preflight_result(
            result,
            required_checks=set(MANDATORY),
            observed_checks=OBSERVED,
            expected_status="not_ready",
            mandatory_order=MANDATORY,
        )

    # The app's caching_sha2_password retry ran inside each attempt, and still
    # produced one stable verdict per call rather than a different one.
    assert source.connects > 2
    assert source.disposed == len(source.urls)


# =============================================================================
# Resource and input shapes
# =============================================================================


@pytest.mark.preflight_conformance(rule="F016", scenario="mixed_resources")
async def test_two_sources_are_judged_on_their_own_rows(
    source: SyntheticMySQL,
) -> None:
    """This connector probes one connection per invocation, so its distinct
    resources are distinct sources. A fully readable source and one whose
    listing is denied are judged independently — neither leaks into the
    other's verdict."""
    readable = await _run(host="readable.internal.example")
    assert_preflight_result(
        readable,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert all(check.passed for check in readable.checks)

    source.deny_listing()
    restricted = await _run(host="restricted.internal.example")
    assert_preflight_result(
        restricted,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert (
        next(c for c in restricted.checks if c.name == "connectivity").passed is False
    )
    assert next(c for c in restricted.checks if c.name == "auth").passed is True

    # Each invocation built its own connection to its own host: the second
    # verdict cannot have been carried over from the first.
    assert "readable.internal.example" in source.urls[0]
    assert "restricted.internal.example" in source.urls[-1]


@pytest.mark.preflight_conformance(rule="F016", scenario="extraction_fallback")
async def test_probe_and_extraction_read_the_same_surface(
    source: SyntheticMySQL,
) -> None:
    """This app has no in-app preflight retry, so the gate's continuation rests
    on probe/extraction parity: the advisory probe must read the same thing
    extraction reads. Both statements target information_schema.TABLES with
    the same filter parameters, and the same injected refusal reaches both —
    so READY with a passing connectivity row is not claiming a capability the
    crawl lacks."""
    from app.mysql import MySQLApp  # noqa: PLC0415 — extraction SQL lives here

    extraction_sql = MySQLApp.fetch_table_sql
    for statement in (_TABLES_CHECK_SQL, extraction_sql):
        assert "information_schema.TABLES" in statement.replace(
            "INFORMATION_SCHEMA.TABLES", "information_schema.TABLES"
        )

    source.deny_listing()
    source.answer(extraction_sql, _grant_denied())

    blocked = await _run()
    assert_preflight_result(
        blocked,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    connectivity = next(c for c in blocked.checks if c.name == "connectivity")
    assert connectivity.passed is False

    # The same refusal, on the statement the crawl issues.
    client = SQLClient()
    with pytest.raises(SqlPandasResultError):
        await client.get_results(extraction_sql)

    # And the recovered source produces a clean, truthful READY.
    source.responses.clear()
    recovered = await _run()
    assert_preflight_result(
        recovered,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert all(check.passed for check in recovered.checks)


@pytest.mark.preflight_conformance(rule="F016", scenario="credential_entrypoint_shapes")
async def test_every_supported_credential_shape_produces_a_typed_verdict(
    source: SyntheticMySQL,
) -> None:
    """Each shape the entrypoint accepts resolves to a truthful verdict —
    including the SDR agent's dotted spelling, which the app flattens itself,
    and the missing-field case, which must block rather than pass vacuously."""
    ready = await _run()
    assert_preflight_result(
        ready,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )

    # extra.* keys are nested by the handler before the client sees them.
    with_database = await _run(**{"extra.database": "analytics"})
    assert_preflight_result(
        with_database,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )

    # SDR / agent mode. The app flattens basic.username / basic.password in
    # SQLClient.load; the connection URL it built proves the flattening ran
    # rather than silently connecting as nobody.
    dotted = await _run(
        username=None,
        password=None,
        **{"basic.username": "agent_reader", "basic.password": SYNTHETIC_PASSWORD},
    )
    assert_preflight_result(
        dotted,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert "agent_reader" in source.urls[-1]

    # A missing required field blocks with a typed verdict.
    incomplete = await _run(host=None)
    assert_preflight_result(
        incomplete,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="not_ready",
        mandatory_order=MANDATORY,
        expected_errors={"auth": {"code": "AUTH_MYSQL_PREFLIGHT"}},
    )


# =============================================================================
# Probe lifetime: absence and cancellation
# =============================================================================


@pytest.mark.preflight_conformance(rule="F016", scenario="no_probe")
async def test_missing_host_blocks_without_touching_the_source(
    source: SyntheticMySQL,
) -> None:
    """A missing host is decided from the credentials alone: the app's
    connection-string builder refuses before any engine exists. No probe is
    attempted, and the verdict is still a typed NOT_READY rather than a
    vacuous READY."""
    result = await _run(host=None)

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="not_ready",
        mandatory_order=MANDATORY,
    )
    assert {check.name for check in result.checks} == {"auth"}
    assert source.urls == []
    assert source.connects == 0
    assert source.queries == []


@pytest.mark.preflight_conformance(rule="F016", scenario="cancellation_cleanup")
async def test_external_cancellation_propagates_and_disposes_the_engine(
    source: SyntheticMySQL,
) -> None:
    """External cancellation must be preserved, not swallowed into a verdict,
    and must not leave the engine behind. The budget here bounds how long
    cancellation may take to land and clean up — a property that holds
    whether or not the handler reads it."""
    probing = asyncio.Event()

    async def _never_answers() -> pd.DataFrame:
        probing.set()
        await asyncio.sleep(30)
        return pd.DataFrame({"count": [0]})

    source.answer(_TABLES_CHECK_SQL, _never_answers)

    budget = 5
    task = asyncio.create_task(_run(budget=budget))
    await asyncio.wait_for(probing.wait(), timeout=budget)

    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    elapsed = time.monotonic() - started

    assert_probe_lifetime(
        elapsed=elapsed,
        budget=float(budget),
        background_stopped=source.disposed == len(source.urls) == 1,
    )

    # The source is untouched afterwards: a recovered run is truthful.
    source.responses.clear()
    result = await _run(budget=budget)
    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )


# =============================================================================
# Safe typed output
# =============================================================================


@pytest.mark.preflight_conformance(rule="F016", scenario="typed_safe_output")
async def test_password_never_reaches_the_output_or_the_logs(
    source: SyntheticMySQL, captured_logs: io.StringIO
) -> None:
    """The failure path is the dangerous one: SQLAlchemy embeds the connection
    URL — password included — in its error text, and that text travels into
    ``cause_repr``, which reaches Temporal history and the connector-pulse
    check matrix. Neither the verdict nor the logs may carry it."""
    source.connect_error = _driver_error(
        ERRNO_ACCESS_DENIED,
        "Access denied for user 'atlan_reader'@'10.0.0.1' using "
        f"mysql+aiomysql://atlan_reader:{SYNTHETIC_PASSWORD}@mysql:3306",
    )

    result = await _run()

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="not_ready",
        mandatory_order=MANDATORY,
        synthetic_secrets=(SYNTHETIC_PASSWORD,),
        captured_logs=captured_logs.getvalue(),
        expected_errors={
            "auth": {
                "category": "AUTH",
                "code": "AUTH_MYSQL_PREFLIGHT",
                "retryable": False,
                "audience": "USER",
            }
        },
    )
    assert SYNTHETIC_PASSWORD not in result.model_dump_json()
    assert SYNTHETIC_PASSWORD not in captured_logs.getvalue()


# =============================================================================
# Recovery, hangs and budgets
# =============================================================================


@pytest.mark.preflight_conformance(rule="F016", scenario="recoverable_transient")
async def test_server_blip_raises_then_clears_on_the_next_attempt(
    source: SyntheticMySQL,
) -> None:
    """A lost connection is "ask me later", not a verdict: the handler raises
    the typed retryable leaf rather than returning one, and the next gate
    attempt against a recovered source returns a clean READY.

    Returning instead would force a choice between two wrong answers — READY
    carrying a failed mandatory row, which greenlights a source nothing
    verified, or NOT_READY, which aborts a healthy run on a server restart."""
    source.connect_error = _driver_error(
        ERRNO_CONNECTION_LOST, "Lost connection to MySQL server during query"
    )

    with pytest.raises(SourceRestartingError) as blip:
        await _run()

    details = blip.value.to_failure_details()
    assert details.retryable is True
    assert details.code == "SOURCE_UNAVAILABLE_MYSQL_CONNECTION_LOST"
    assert details.suggested_action

    source.connect_error = None
    result = await _run()

    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )
    assert all(check.passed for check in result.checks)


@pytest.mark.preflight_conformance(rule="F016", scenario="hung_probe")
async def test_unanswered_probe_stays_inside_the_budget_and_cleans_up(
    source: SyntheticMySQL,
) -> None:
    """A source that accepts the connection and then never answers must not
    outlive the gate's budget, and must leave no engine behind. The overrun is
    raised as a typed retryable leaf: a source that did not answer has said
    nothing about whether it is readable."""
    probing = asyncio.Event()

    async def _never_answers() -> pd.DataFrame:
        probing.set()
        await asyncio.sleep(30)
        return pd.DataFrame({"count": [0]})

    source.answer(_TEST_AUTH_SQL, _never_answers)

    budget = 2
    started = time.monotonic()
    with pytest.raises(PreflightProbeTimeoutError) as hung:
        await _run(budget=budget)
    elapsed = time.monotonic() - started

    assert probing.is_set(), "the probe never started, so nothing was bounded"
    assert hung.value.to_failure_details().retryable is True
    # The connect deadline sits strictly inside the enforced budget, so the
    # driver cannot be the thing that overruns it.
    assert _connect_timeouts(source) == [1]
    assert_probe_lifetime(
        elapsed=elapsed,
        budget=float(budget),
        background_stopped=source.disposed == len(source.urls) == 1,
    )

    source.responses.clear()
    result = await _run(budget=budget)
    assert_preflight_result(
        result,
        required_checks=set(MANDATORY),
        observed_checks=OBSERVED,
        expected_status="ready",
        mandatory_order=MANDATORY,
    )


@pytest.mark.preflight_conformance(rule="F016", scenario="budget_retry")
async def test_probe_deadline_shrinks_with_the_remaining_budget(
    source: SyntheticMySQL,
) -> None:
    """``timeout_seconds`` is the budget *remaining* for this attempt, so a
    later gate attempt gets a smaller one and the probe must shrink with it. A
    deadline that can outlive its budget makes the gate's cancel decorative."""
    budgets = (60, 10, 2)

    for index, budget in enumerate(budgets, start=1):
        started = time.monotonic()
        result = await _run(budget=budget)
        elapsed = time.monotonic() - started

        assert_preflight_result(
            result,
            required_checks=set(MANDATORY),
            observed_checks=OBSERVED,
            expected_status="ready",
            mandatory_order=MANDATORY,
        )
        # Measured against THIS attempt's own remaining budget. Timing the
        # three together against their sum would pass on any timing at all —
        # only the tightest budget constrains anything, and the sum hides it.
        assert_probe_lifetime(
            elapsed=elapsed,
            budget=float(budget),
            background_stopped=source.disposed == index,
        )

    deadlines = _connect_timeouts(source)
    assert len(deadlines) == len(budgets)
    for budget, deadline in zip(budgets, deadlines):
        assert deadline < budget, "probe deadline must stay inside its budget"
    assert deadlines == sorted(deadlines, reverse=True), (
        "a shrinking remaining budget must shrink the probe"
    )
