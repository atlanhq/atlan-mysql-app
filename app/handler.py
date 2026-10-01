"""MySQL v3 Handler — auth, preflight, metadata endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from application_sdk.errors import AppError
from application_sdk.handler import (
    AuthInput,
    AuthOutput,
    AuthStatus,
    Handler,
    HandlerCredential,
    MetadataInput,
    PreflightCheck,
    PreflightInput,
    PreflightOutput,
    PreflightStatus,
    SqlMetadataObject,
    SqlMetadataOutput,
)

from .client import SQLClient
from .constants import DATABASE_PLACEHOLDER
from .failures import (
    MetadataFetchError,
    MetadataHostMissingError,
    PreflightAuthError,
    PreflightProbeTimeoutError,
    TableListingError,
    transient_failure,
)


# SQL for handler endpoints
_TEST_AUTH_SQL = (
    (Path(__file__).parent / "sql" / "test_authentication.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
)

_TABLES_CHECK_SQL = (
    (Path(__file__).parent / "sql" / "tables_check.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
    .replace("{normalized_exclude_regex}", "^$")  # exclude nothing
    .replace("{normalized_include_regex}", ".*")  # include everything
    .replace("{temp_table_regex_sql}", "")  # no temp-table filter
)

_FILTER_METADATA_SQL = (
    (Path(__file__).parent / "sql" / "filter_metadata.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
)


# The gate hands preflight_check the budget *remaining* for the whole check,
# so a later attempt gets a smaller one. The probe spends a fraction of it and
# leaves the rest for building and returning the verdict: a probe allowed the
# whole budget can only finish by overrunning it, which makes the gate's
# deadline decorative.
_PROBE_BUDGET_FRACTION = 0.8

# Never longer than the connect timeout the app ships as its default, whatever
# the gate's budget is. A generous budget is not a reason to wait longer on a
# host that is not answering.
_CONNECT_TIMEOUT_CAP_SECONDS = 5


def _probe_deadline(remaining: float | None) -> float | None:
    """The slice of the gate's remaining budget this probe may spend.

    ``None`` when the gate supplied no budget — the handler then imposes no
    deadline of its own, which is the behaviour every caller had before.
    """
    if remaining is None or remaining <= 0:
        return None
    return remaining * _PROBE_BUDGET_FRACTION


def _connect_timeout(deadline: float | None) -> int:
    """Whole seconds for the driver's connect attempt, inside `deadline`.

    Floored rather than rounded so the connect attempt stays inside the
    deadline, with a one-second floor because a connect timeout of zero means
    "no timeout" to the driver. Below a ~1.25s deadline the floor wins and this
    value exceeds it; the caller's `wait_for` still bounds the probe, so the
    overrun is capped either way — the driver simply stops being the tighter
    of the two limits. The gate does not hand out budgets that small today.
    """
    if deadline is None:
        return _CONNECT_TIMEOUT_CAP_SECONDS
    return max(1, int(min(_CONNECT_TIMEOUT_CAP_SECONDS, deadline)))


def _creds_to_dict(credentials: list[HandlerCredential]) -> dict[str, Any]:
    """Convert v3 HandlerCredential list to a flat credentials dict."""
    cred_dict: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for cred in credentials:
        if cred.key.startswith("extra."):
            extra[cred.key[len("extra.") :]] = cred.value
        else:
            cred_dict[cred.key] = cred.value
    if extra:
        cred_dict["extra"] = extra
    return cred_dict


class MySQLAppHandler(Handler):
    """MySQL v3 handler for auth, preflight, and metadata endpoints."""

    async def test_auth(self, input: AuthInput) -> AuthOutput:
        """Test MySQL connectivity with provided credentials."""
        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            await client.load(credentials=creds)
            await client.get_results(_TEST_AUTH_SQL)
            return AuthOutput(
                status=AuthStatus.SUCCESS, message="Authentication successful"
            )
        except Exception as e:
            err = transient_failure(e) or PreflightAuthError(cause=e)
            return AuthOutput(status=AuthStatus.FAILED, error=err.to_failure_details())
        finally:
            await client.close()

    async def preflight_check(self, input: PreflightInput) -> PreflightOutput:
        """Auth (required, short-circuits the run) + tables (advisory).

        A definitive auth failure is NOT_READY. A transient one is not a
        verdict at all: the typed retryable leaf is raised so the gate can ask
        again, rather than reported as a failed mandatory row under a green
        light. Auth passing with a failed advisory tables check stays READY,
        with the failure visible as a typed row — extraction can proceed.

        The whole check is bounded by the slice of the gate's remaining budget
        `_probe_deadline` allows. Overrunning it is not a verdict either: a
        source that did not answer has said nothing about whether it is
        readable, so the typed retryable leaf is raised and the gate asks again.
        """
        deadline = _probe_deadline(input.timeout_seconds)
        try:
            return await asyncio.wait_for(
                self._run_preflight_probes(input, deadline), timeout=deadline
            )
        # A deadline overrun is not an expected *source* failure: the source
        # said nothing, so there is no verdict to report, and returning
        # NOT_READY would abort a healthy run because a server was briefly
        # slow. `transient_failure` classifies it into the typed retryable
        # leaf and this only re-raises what it returned — the same shape as
        # the transient auth blip below, and as `_as_gate_transient` in
        # atlan-openapi-app, F008's own compliant example. The leaf is a
        # SourceUnavailableError with retryable=True, so the gate asks again.
        except TimeoutError as e:
            overrun = transient_failure(e) or PreflightProbeTimeoutError(cause=e)
            raise overrun from e

    async def _run_preflight_probes(
        self, input: PreflightInput, deadline: float | None
    ) -> PreflightOutput:
        """The probes themselves, run under the caller's deadline.

        Split out so the deadline is enforced from *outside* the broad
        ``except Exception`` clauses below: raised inside them, a timeout would
        be classified as a source failure and reported as a verdict, which is
        the one thing it must never become.
        """
        client = SQLClient(probe_timeout=_connect_timeout(deadline))
        try:
            creds = _creds_to_dict(input.credentials)
            try:
                await client.load(credentials=creds)
                await client.get_results(_TEST_AUTH_SQL)
            except Exception as e:
                transient = transient_failure(e)
                if transient is not None:
                    # A blip is "ask me later", not a verdict. Raising the typed
                    # retryable leaf lets the gate retry; returning a verdict
                    # would force a choice between two wrong answers — READY
                    # carrying a failed *mandatory* row (a green light nothing
                    # verified) or NOT_READY, which aborts a healthy run on a
                    # server restart. This is the shape atlan-openapi-app uses,
                    # and the one F016's recoverable_transient scenario asserts.
                    raise transient from e
                auth_check = PreflightCheck(
                    name="auth",
                    passed=False,
                    error=PreflightAuthError(cause=e).to_failure_details(),
                )
                # The checks list is spelled inline at every PreflightOutput
                # call rather than accumulated with .append(): static analysis
                # can only resolve mandatory/advisory roles from a literal list,
                # and an accumulator reads as an unresolved aggregation (F019).
                # Same verdicts, same rows, same order.
                return PreflightOutput(
                    status=PreflightStatus.NOT_READY, checks=[auth_check]
                )

            # Connectivity is advisory: extraction can still proceed when the
            # table listing fails, which is what READY means now that PARTIAL
            # is deprecated. The failed row carries the detail.
            return PreflightOutput(
                status=PreflightStatus.READY,
                checks=[
                    PreflightCheck(name="auth", passed=True, message="Authenticated"),
                    await self._check_connectivity(client),
                ],
            )
        finally:
            await client.close()

    async def _check_connectivity(self, client: SQLClient) -> PreflightCheck:
        """List accessible tables. A source failure becomes a failed row, never a raise."""
        try:
            result = await client.get_results(_TABLES_CHECK_SQL)
        except Exception as e:
            blip = transient_failure(e)
            listing_failure = blip if blip is not None else TableListingError(cause=e)
            return PreflightCheck(
                name="connectivity",
                passed=False,
                error=listing_failure.to_failure_details(),
            )
        count = len(result) if result is not None else 0
        return PreflightCheck(
            name="connectivity",
            passed=True,
            message=f"Found {count} accessible tables",
        )

    async def fetch_metadata(self, input: MetadataInput) -> SqlMetadataOutput:
        """Fetch schema metadata for the UI tree."""
        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            # Log credential keys (not values) so we can tell whether the
            # marketplace credential-resolution layer populated the input.
            # Values would leak secrets; keys alone are enough to diagnose.

            if not creds.get("host"):
                raise MetadataHostMissingError(
                    message="fetch_metadata called with no host in credentials — "
                    "credential resolution may not have completed yet",
                )

            await client.load(credentials=creds)

            result = await client.get_results(_FILTER_METADATA_SQL)

            objects = []
            if result is not None:
                for _, row in result.iterrows():
                    objects.append(
                        SqlMetadataObject(
                            TABLE_CATALOG=str(
                                row.get("database_name", DATABASE_PLACEHOLDER)
                            ),
                            TABLE_SCHEMA=str(row.get("schema_name", "")),
                        )
                    )

            return SqlMetadataOutput(objects=objects)
        except Exception as e:
            if isinstance(e, AppError):
                raise
            raise MetadataFetchError(cause=e) from e
        finally:
            await client.close()
