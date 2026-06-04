"""MySQL v3 Handler — auth, preflight, metadata endpoints."""

from __future__ import annotations

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
from application_sdk.observability.logger_adaptor import get_logger

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER
from app.failures import MetadataFetchError, MetadataHostMissingError
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


def _control_config_from_request(
    credentials: list[HandlerCredential] | None,
    connection_config: Any | None,
) -> dict[str, Any]:
    """Combine credentials and connection_config into one control-config dict.

    Precedence (REQ-925):

    1. ``clonedInformationSchema`` from the **credential extras**
       (``extra.clonedInformationSchema`` — declared in
       ``credentialAuthOptions[*].extraFields`` in ``contract/app.pkl``,
       persisted by the marketplace under the credential's ``extra``
       namespace, available to ``test_auth`` / ``preflight_check`` /
       ``fetch_metadata`` at design time).
    2. ``clonedInformationSchema`` from the **Control Config JSON** under
       Advanced Config (legacy workflow-runtime fallback for existing
       workflows that configured the mirror via the JSON blob).

    When both are set, the credential value wins — silently. We don't warn
    because the credential side is unambiguously authoritative.

    Why ``extra.<name>`` and not a top-level ``credentialCommonFields``
    entry: the marketplace credential-persistence layer drops top-level
    custom fields outside the well-known set (``host`` / ``port`` etc.).
    Sibling connectors (``atlan-databricks-app``'s ``__http_path``,
    ``atlan-bigquery-app``'s ``project_id``) thread non-auth design-time
    fields through ``extraFields`` exactly because that's the persistence
    path the marketplace honours. See the comment block above
    ``credentialAuthOptions`` in ``contract/app.pkl`` for the full
    rationale and bug history.
    """
    config = dict(extract_control_config(connection_config))
    if credentials:
        creds_dict = _creds_to_dict(credentials)
        value = (creds_dict.get("extra") or {}).get("clonedInformationSchema")
        if isinstance(value, str) and value.strip():
            config["clonedInformationSchema"] = value.strip()
    return config


def _resolve_handler_sql(
    template: str,
    credentials: list[HandlerCredential] | None,
    connection_config: Any | None,
) -> str:
    """Resolve handler-side SQL placeholders from per-request config.

    Reads ``clonedInformationSchema`` from credentials first, then falls
    back to the legacy Control Config JSON on ``connection_config``. With
    neither configured, the resulting SQL is byte-identical to pre-REQ-925
    behavior.
    """
    config = _control_config_from_request(credentials, connection_config)
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
            logger.exception("MySQL auth test failed")
            return AuthOutput(status=AuthStatus.FAILED, message=str(e))
        finally:
            await client.close()

    async def preflight_check(self, input: PreflightInput) -> PreflightOutput:
        """Run preflight checks: auth + connectivity.

        ``{information_schema}`` in the connectivity check SQL is resolved
        per-request — primarily from the credential record's
        ``clonedInformationSchema`` field (the canonical location, REQ-925)
        and falling back to ``input.connection_config``'s legacy Control
        Config JSON. Either path lets preflight succeed against a
        customer's mirror schema (e.g. ``atlan_meta``) without granting
        ``SELECT`` on the native ``information_schema``.
        """
        checks: list[PreflightCheck] = []

        tables_check_sql = _resolve_handler_sql(
            _TABLES_CHECK_SQL_TEMPLATE,
            input.credentials,
            getattr(input, "connection_config", None),
        )

        client = SQLClient()
        try:
            creds = _creds_to_dict(input.credentials)
            try:
                await client.load(credentials=creds)
            except Exception as e:
                logger.warning("Auth preflight check failed", exc_info=True)
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
                logger.warning("Auth preflight check failed", exc_info=True)
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
                logger.warning("Connectivity preflight check failed", exc_info=True)
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

        Resolves ``{information_schema}`` per-request from the credential
        record's ``clonedInformationSchema`` field first, falling back to
        the legacy Control Config JSON on ``input.connection_config``.
        Falls back to ``information_schema`` when no override is present.
        """
        filter_metadata_sql = _resolve_handler_sql(
            _FILTER_METADATA_SQL_TEMPLATE,
            input.credentials,
            getattr(input, "connection_config", None),
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
                raise MetadataHostMissingError(
                    message="fetch_metadata called with no host in credentials — "
                    "credential resolution may not have completed yet",
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
            if isinstance(e, AppError):
                raise
            raise MetadataFetchError(cause=e) from e
        finally:
            await client.close()
