"""MySQL serving surface on atlan-server-sdk.

Standalone:

    uvicorn --factory mysql_server:get_asgi_app --port 8000

Consolidated: the common-api-server imports :func:`get_asgi_app` through this
package's ``atlan.app_server`` entry point and mounts it under the ``mysql``
Host label.

Verdict semantics are the worker's, deliberately: auth is required and
short-circuits, the tables probe is advisory, and a transient blip reports
PARTIAL rather than NOT_READY — a hard gate must not abort a run because the
source hiccuped.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from server_sdk import build_asgi_app
from server_sdk.handler.contracts import (
    AuthInput,
    AuthOutput,
    AuthStatus,
    MetadataInput,
    PreflightCheck,
    PreflightInput,
    PreflightOutput,
    PreflightStatus,
    SqlMetadataObject,
    SqlMetadataOutput,
)
from server_sdk.handler.sql import SQLHandler
from server_sdk.observability.logger_adaptor import get_logger

from mysql_server.client import MySQLServerClient
from mysql_server.errors import (
    MetadataHostMissingError,
    PreflightAuthError,
    TableListingError,
    transient_failure,
)
from mysql_server.queries import (
    DATABASE_PLACEHOLDER,
    FILTER_METADATA_SQL,
    TABLES_CHECK_SQL,
    TEST_AUTH_SQL,
)

logger = get_logger(__name__)

_PACKAGED_GENERATED_DIR = Path(__file__).resolve().parent / "generated"


def _creds_to_dict(credentials: Any) -> dict[str, Any]:
    """Flatten the wire credential list, hoisting ``extra.*`` into ``extra``."""
    flat: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for cred in credentials or []:
        key = getattr(cred, "key", None)
        value = getattr(cred, "value", None)
        if key is None:
            continue
        if key.startswith("extra."):
            extra[key[len("extra.") :]] = value
        else:
            flat[key] = value
    if extra:
        flat["extra"] = extra
    return flat


class MySQLServerHandler(SQLHandler):
    """auth / preflight / metadata for MySQL."""

    client_class = MySQLServerClient

    async def test_auth(self, input: AuthInput) -> AuthOutput:
        client = MySQLServerClient()
        try:
            await client.load(credentials=_creds_to_dict(input.credentials))
            await client.get_results(TEST_AUTH_SQL)
            return AuthOutput(
                status=AuthStatus.SUCCESS, message="Authentication successful"
            )
        except Exception:  # noqa: BLE001 — a probe reports, never raises
            logger.debug("MySQL auth test failed", exc_info=True)
            return AuthOutput(status=AuthStatus.FAILED, message="Authentication failed")
        finally:
            await client.close()

    async def preflight_check(self, input: PreflightInput) -> PreflightOutput:
        """Auth (required, short-circuits) + tables (advisory).

        NOT_READY only when auth fails definitively; PARTIAL when a blip hid the
        verdict, or auth passed but the advisory tables probe failed; READY when
        both pass.
        """
        checks: list[PreflightCheck] = []
        client = MySQLServerClient()
        try:
            creds = _creds_to_dict(input.credentials)
            try:
                await client.load(credentials=creds)
                await client.get_results(TEST_AUTH_SQL)
            except Exception as exc:  # noqa: BLE001 — a probe reports, never raises
                logger.debug("Auth preflight check failed", exc_info=True)
                transient = transient_failure(exc)
                failure = transient or PreflightAuthError(cause=exc)
                checks.append(
                    PreflightCheck(
                        name="auth",
                        passed=False,
                        message=str(failure),
                        error=failure.to_failure_details(),
                    )
                )
                return PreflightOutput(
                    status=(
                        PreflightStatus.PARTIAL
                        if transient
                        else PreflightStatus.NOT_READY
                    ),
                    checks=checks,
                )

            checks.append(
                PreflightCheck(name="auth", passed=True, message="Authenticated")
            )

            try:
                result = await client.get_results(TABLES_CHECK_SQL)
                count = len(result) if result is not None else 0
                checks.append(
                    PreflightCheck(
                        name="connectivity",
                        passed=True,
                        message=f"Found {count} accessible tables",
                    )
                )
                status = PreflightStatus.READY
            except Exception as exc:  # noqa: BLE001 — advisory probe
                logger.debug("Connectivity preflight check failed", exc_info=True)
                blip = transient_failure(exc)
                failure = blip or TableListingError(cause=exc)
                checks.append(
                    PreflightCheck(
                        name="connectivity",
                        passed=False,
                        message=str(failure),
                        error=failure.to_failure_details(),
                    )
                )
                status = PreflightStatus.PARTIAL
            return PreflightOutput(status=status, checks=checks)
        finally:
            await client.close()

    async def fetch_metadata(self, input: MetadataInput) -> SqlMetadataOutput:
        client = MySQLServerClient()
        try:
            creds = _creds_to_dict(input.credentials)
            # Keys, never values: enough to tell whether credential resolution
            # populated the input, without putting secrets in a log line.
            logger.info(
                "fetch_metadata: %d credentials received, keys=%s",
                len(input.credentials or []),
                sorted(creds.keys()),
            )
            if not creds.get("host"):
                raise MetadataHostMissingError(
                    message=(
                        "fetch_metadata called with no host in credentials — "
                        "credential resolution may not have completed yet"
                    ),
                )
            await client.load(credentials=creds)
            result = await client.get_results(FILTER_METADATA_SQL)

            objects: list[SqlMetadataObject] = []
            for row in result or []:
                objects.append(
                    SqlMetadataObject(
                        TABLE_CATALOG=str(
                            row.get("database_name", DATABASE_PLACEHOLDER)
                        ),
                        TABLE_SCHEMA=str(row.get("schema_name", "")),
                    )
                )
            return SqlMetadataOutput(objects=objects)
        except Exception as exc:  # noqa: BLE001 — boundary: never 500 to the UI
            # The SDK's generic fetch_metadata documents this contract: an empty
            # list to the connector form, never a 500. Overriding the method
            # does not exempt us from it — a raised error here renders as
            # "Internal server error" in the schema picker, which tells the
            # customer nothing and looks like our fault even when the source is
            # simply unreachable.
            logger.warning(
                "MySQL fetch_metadata failed, returning no objects: %s",
                type(exc).__name__,
            )
            return SqlMetadataOutput(objects=[])
        finally:
            await client.close()


def _generated_dir() -> Path:
    """Env override -> contracts packaged in this wheel -> the app-tree default.

    In the consolidated host the app tree is absent, so the packaged copy is
    what lets /manifest answer at all. The override is honoured only when it
    exists: an empty value resolves to the process CWD, which in the host would
    make the configmap routes enumerate every co-hosted app's contracts.
    """
    override = os.environ.get("ATLAN_CONTRACT_GENERATED_DIR", "").strip()
    if override and Path(override).is_dir():
        return Path(override)
    if _PACKAGED_GENERATED_DIR.is_dir():
        return _PACKAGED_GENERATED_DIR
    return Path("app/generated")


def get_asgi_app() -> FastAPI:
    """Return the MySQL server as a standalone / Host-routable ASGI app."""
    return build_asgi_app(
        MySQLServerHandler(),
        app_name="mysql",
        generated_dir=_generated_dir(),
        # The IMPORT name of this package — not the app name, not the
        # distribution name. Without it server_sdk cannot digest this app's
        # source and every response stamps src=unknown.
        app_package="mysql_server",
    )
