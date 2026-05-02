"""MySQL v3 Handler — auth, preflight, metadata endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER

logger = get_logger(__name__)

# SQL for handler endpoints
_TEST_AUTH_SQL = (
    (Path(__file__).parent.parent / "sql" / "test_authentication.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
)

_TABLES_CHECK_SQL = (
    (Path(__file__).parent.parent / "sql" / "tables_check.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
    .replace("{normalized_exclude_regex}", "^$")  # exclude nothing
    .replace("{normalized_include_regex}", ".*")  # include everything
    .replace("{temp_table_regex_sql}", "")  # no temp-table filter
)

_FILTER_METADATA_SQL = (
    (Path(__file__).parent.parent / "sql" / "filter_metadata.sql")
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
        except Exception as e:
            logger.error("MySQL auth test failed: %s", e)
            return AuthOutput(status=AuthStatus.FAILED, message=str(e))
        finally:
            await client.close()

    async def preflight_check(self, input: PreflightInput) -> PreflightOutput:
        """Run preflight checks: auth + connectivity."""
        checks: list[PreflightCheck] = []

        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            try:
                await client.load(credentials=creds)
            except Exception as e:
                checks.append(
                    PreflightCheck(
                        name="auth", passed=False, message=f"Connection failed: {e}"
                    )
                )
                return PreflightOutput(status=PreflightStatus.NOT_READY, checks=checks)

            # Auth check
            try:
                await client.get_results(_TEST_AUTH_SQL)
                checks.append(
                    PreflightCheck(name="auth", passed=True, message="Authenticated")
                )
            except Exception as e:
                checks.append(
                    PreflightCheck(
                        name="auth", passed=False, message=f"Auth failed: {e}"
                    )
                )
                return PreflightOutput(status=PreflightStatus.NOT_READY, checks=checks)

            # Connectivity check — can we list tables?
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
            except Exception as e:
                checks.append(
                    PreflightCheck(
                        name="connectivity",
                        passed=False,
                        message=f"Table check failed: {e}",
                    )
                )

            all_passed = all(c.passed for c in checks)
            return PreflightOutput(
                status=PreflightStatus.READY
                if all_passed
                else PreflightStatus.NOT_READY,
                checks=checks,
            )
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
                raise ValueError(
                    "fetch_metadata called with no host in credentials — "
                    "credential resolution may not have completed yet"
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
            logger.error("Failed to fetch metadata: %s", e, exc_info=True)
            raise
        finally:
            await client.close()
