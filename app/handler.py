"""MySQL v3 Handler — auth, preflight, metadata endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from application_sdk.errors import AppError, AuthError
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
from app.failures import MetadataFetchError, MetadataHostMissingError

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
        except Exception:
            logger.error("MySQL auth test failed", exc_info=True)  # noqa: G201
            return AuthOutput(status=AuthStatus.FAILED, message="Authentication failed")
        finally:
            await client.close()

    async def preflight_check(self, input: PreflightInput) -> PreflightOutput:
        """Auth (required, short-circuits the run) + tables (advisory).

        NOT_READY only when auth fails; PARTIAL when auth passes but the
        advisory tables check fails; READY when both pass.
        """
        checks: list[PreflightCheck] = []
        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            try:
                await client.load(credentials=creds)
                await client.get_results(_TEST_AUTH_SQL)
            # Suppression owner: @cmgrote. Review by 2027-03-02, or sooner if the
            # suite resolves the conflict — either E004 accepting DEBUG+exc_info
            # inside a preflight_check, or P047 exempting a broad-catch probe.
            # Delete this suppression when it does; it is not a standing exemption.
            # conformance: ignore[E004] a preflight probe must report a verdict, never crash, so the broad catch is deliberate; E004's sanctioned exc_info WARNING is banned inside preflight_check by P047
            except Exception as e:
                # DEBUG, not WARNING: the preflight gate owns the customer-facing
                # outcome row and levels it from the verdict — ERROR when the run is
                # blocked, as it is here. A handler-authored WARNING is both a
                # duplicate of that row and invisible under the customer's default
                # ERROR filter (P047 / FND-901). DEBUG keeps the traceback for
                # engineers without adding a second customer-visible record.
                logger.debug("Auth preflight check failed", exc_info=True)
                checks.append(
                    PreflightCheck(
                        name="auth",
                        passed=False,
                        error=AuthError(  # type: ignore[arg-type]
                            message="Could not authenticate to the MySQL source.",
                            suggested_action=(
                                "Verify the host, port, and credentials, and that "
                                "the database is reachable from Atlan."
                            ),
                            cause=e,
                        ),
                    )
                )
                return PreflightOutput(status=PreflightStatus.NOT_READY, checks=checks)
            checks.append(
                PreflightCheck(name="auth", passed=True, message="Authenticated")
            )

            try:
                result = await client.get_results(_TABLES_CHECK_SQL)
                count = len(result) if result is not None else 0
                checks.append(
                    PreflightCheck(
                        name="connectivity",
                        passed=True,
                        message=f"Found {count} accessible tables",
                    )
                )
                status = PreflightStatus.READY
            # Suppression owner: @cmgrote. Review by 2027-03-02, or sooner if the
            # suite resolves the conflict — either E004 accepting DEBUG+exc_info
            # inside a preflight_check, or P047 exempting a broad-catch probe.
            # Delete this suppression when it does; it is not a standing exemption.
            # conformance: ignore[E004] a preflight probe must report a verdict, never crash, so the broad catch is deliberate; E004's sanctioned exc_info WARNING is banned inside preflight_check by P047
            except Exception:
                # DEBUG, not WARNING: this check is advisory, so the gate emits the
                # single WARNING outcome row itself (keyed on any failed check) —
                # P047 bans the handler from logging it. DEBUG keeps the traceback
                # for engineers without duplicating the gate's record.
                logger.debug("Connectivity preflight check failed", exc_info=True)
                checks.append(
                    PreflightCheck(
                        name="connectivity",
                        passed=False,
                        message="Table check failed",
                    )
                )
                status = PreflightStatus.PARTIAL
            return PreflightOutput(status=status, checks=checks)
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
        # conformance: ignore[E004] boundary catch-and-translate; re-raises AppErrors as-is and wraps everything else in a typed MetadataFetchError with `from e`
        except Exception as e:
            if isinstance(e, AppError):
                raise
            raise MetadataFetchError(cause=e) from e
        finally:
            await client.close()
