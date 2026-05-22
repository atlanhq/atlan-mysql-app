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
from app.utils import (
    extract_control_config,
    resolve_excluded_schemas,
    resolve_information_schema,
)

logger = get_logger(__name__)

# SQL templates for handler endpoints. ``{information_schema}`` is kept
# unresolved at module-import time and substituted per-request from
# control-config on the incoming ``PreflightInput``/``MetadataInput``.
# ``BaseConnectionConfig`` has ``model_config = {'extra': 'allow', ...}`` so
# the marketplace UI's Custom Control Config passes through verbatim.
_TEST_AUTH_SQL = (
    (Path(__file__).parent.parent / "sql" / "test_authentication.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
)

_TABLES_CHECK_SQL_TEMPLATE = (
    (Path(__file__).parent.parent / "sql" / "tables_check.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
    .replace("{normalized_exclude_regex}", "^$")  # exclude nothing
    .replace("{normalized_include_regex}", ".*")  # include everything
    .replace("{temp_table_regex_sql}", "")  # no temp-table filter
)

_FILTER_METADATA_SQL_TEMPLATE = (
    (Path(__file__).parent.parent / "sql" / "filter_metadata.sql")
    .read_text()
    .strip()
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
)


def _resolve_handler_sql(template: str, connection_config: Any | None) -> str:
    """Resolve handler-side SQL placeholders from per-request control-config.

    Pulls control-config from the request's ``connection_config`` (which is
    a ``BaseConnectionConfig`` with ``extra='allow'``, so customer-supplied
    fields like ``clonedInformationSchema`` are preserved) and applies both
    the ``{information_schema}`` and ``{excluded_schemas}`` resolvers. With
    no override configured, the resulting SQL is byte-identical to today's
    behavior.
    """
    config = extract_control_config(connection_config)
    resolved = resolve_information_schema(template, config)
    return resolve_excluded_schemas(resolved, config)


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
        """Run preflight checks: auth + connectivity.

        ``{information_schema}`` in the connectivity check SQL is resolved
        per-request using control-config from ``input.connection_config``.
        That allows preflight to succeed against a customer's mirror schema
        (e.g. ``atlan_meta``) when ``clonedInformationSchema`` is set,
        without granting them ``SELECT`` on the native ``information_schema``.
        """
        checks: list[PreflightCheck] = []

        tables_check_sql = _resolve_handler_sql(
            _TABLES_CHECK_SQL_TEMPLATE, getattr(input, "connection_config", None)
        )

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
                result = await client.get_results(tables_check_sql)
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
        """Fetch schema metadata for the UI tree.

        Resolves ``{information_schema}`` per-request from
        ``input.connection_config`` so the UI tree honors a configured
        mirror schema. Falls back to ``information_schema`` when no
        ``clonedInformationSchema`` override is present.
        """
        filter_metadata_sql = _resolve_handler_sql(
            _FILTER_METADATA_SQL_TEMPLATE, getattr(input, "connection_config", None)
        )

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

            result = await client.get_results(filter_metadata_sql)
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
