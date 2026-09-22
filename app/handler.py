"""MySQL v3 Handler — auth, preflight, metadata endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from application_sdk.errors import AppError, safe_traceback
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
from application_sdk.observability.logger_adaptor import get_logger

from app.client import SQLClient
from app.constants import DATABASE_PLACEHOLDER
from app.failures import (
    MetadataFetchError,
    MetadataHostMissingError,
    PreflightAuthError,
    PreflightProbeTimeoutError,
    TableListingError,
    transient_failure,
)

logger = get_logger(__name__)

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
        # safe_traceback, not exc_info: this is ERROR, so it is emitted in
        # production, and a SQLAlchemy connection error carries the password in
        # its text. Same redaction as the preflight probes below.
        except Exception as e:
            logger.error("MySQL auth test failed: %s", safe_traceback(e))
            return AuthOutput(status=AuthStatus.FAILED, message="Authentication failed")
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
        # F008 wants expected typed failures returned as a verdict rather than
        # raised. A deadline overrun is not an expected *source* failure: the
        # source said nothing, so there is no verdict to report, and returning
        # NOT_READY would abort a healthy run because a server was briefly slow.
        # This is the same fail-open shape the transient auth blip uses below
        # (which F008 accepts, because that one re-raises a classified error
        # rather than constructing one) and the gate-transient re-raise F008's
        # own compliant example sanctions in atlan-openapi-app. The error is a
        # SourceUnavailableError with retryable=True, so the gate asks again.
        # Suppression owner: @cmgrote. Review by 2027-03-02, or when the suite
        # settles how a constructed gate-transient should be spelled.
        except TimeoutError as e:
            # conformance: ignore[F008] a probe overrun is the absence of an answer, not a verdict; raised as a retryable gate-transient so the gate retries instead of aborting the run
            raise PreflightProbeTimeoutError(cause=e) from e

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
                # DEBUG, not WARNING: the preflight gate owns the customer-facing
                # outcome row and levels it from the verdict — ERROR when the run is
                # blocked, as it is here. A handler-authored WARNING is both a
                # duplicate of that row and invisible under the customer's default
                # ERROR filter (F005 / FND-901). DEBUG keeps the traceback for
                # engineers without adding a second customer-visible record.
                #
                # safe_traceback, not exc_info: SQLAlchemy embeds the whole
                # connection string — password included — in its error text, so
                # a raw traceback puts the credential in the log. The SDK omits
                # exc_info at its own load() failure site for this reason; this
                # keeps the frames and redacts the userinfo instead.
                logger.debug("Auth preflight check failed: %s", safe_traceback(e))
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
            auth_check = PreflightCheck(
                name="auth", passed=True, message="Authenticated"
            )

            try:
                result = await client.get_results(_TABLES_CHECK_SQL)
                count = len(result) if result is not None else 0
                tables_check = PreflightCheck(
                    name="connectivity",
                    passed=True,
                    message=f"Found {count} accessible tables",
                )
                status = PreflightStatus.READY
            except Exception as e:
                # DEBUG, not WARNING: this check is advisory, so the gate emits the
                # single WARNING outcome row itself (keyed on any failed check) —
                # F005 bans the handler from logging it. DEBUG keeps the traceback
                # for engineers without duplicating the gate's record.
                # safe_traceback, not exc_info — see the auth probe above.
                logger.debug(
                    "Connectivity preflight check failed: %s", safe_traceback(e)
                )
                blip = transient_failure(e)
                listing_failure = (
                    blip if blip is not None else TableListingError(cause=e)
                )
                tables_check = PreflightCheck(
                    name="connectivity",
                    passed=False,
                    error=listing_failure.to_failure_details(),
                )
                # Advisory check — extraction can still proceed, which is
                # exactly what the SDK says READY means now that PARTIAL is
                # deprecated. The failed row above carries the detail.
                status = PreflightStatus.READY
            return PreflightOutput(status=status, checks=[auth_check, tables_check])
        finally:
            await client.close()

    async def fetch_metadata(self, input: MetadataInput) -> SqlMetadataOutput:
        """Fetch schema metadata for the UI tree."""
        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            # Log credential keys (not values) so we can tell whether the
            # marketplace credential-resolution layer populated the input.
            # Values would leak secrets; keys alone are enough to diagnose.
            logger.info(
                "fetch_metadata: %d credentials received, keys=%s, host=%s",
                len(input.credentials),
                sorted(creds.keys()),
                creds.get("host", "<missing>"),
            )

            if not creds.get("host"):
                raise MetadataHostMissingError(
                    message="fetch_metadata called with no host in credentials — "
                    "credential resolution may not have completed yet",
                )

            await client.load(credentials=creds)

            result = await client.get_results(_FILTER_METADATA_SQL)
            row_count = 0 if result is None else len(result)
            logger.info(
                "fetch_metadata: SQL returned %s (%d rows)",
                "None" if result is None else "DataFrame",
                row_count,
            )

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
