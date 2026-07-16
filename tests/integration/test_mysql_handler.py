"""Integration tests for MySQLAppHandler — real MySQL, no mocks.

Calls handler methods directly (no HTTP layer) against a real MySQL instance
provided by the session-scoped testcontainers fixture. Complements the unit
tests (which mock SQLClient) by verifying the full path through SQLClient to
the database.

Skips gracefully when no MySQL is available (no MYSQL_HOST env var and no
Docker daemon).
"""

from __future__ import annotations

import os

import pytest
from application_sdk.handler import (
    AuthInput,
    AuthStatus,
    HandlerCredential,
    MetadataInput,
    PreflightInput,
    PreflightStatus,
)

from app.handler import MySQLAppHandler

pytestmark = pytest.mark.integration


def _creds(
    *,
    host: str | None = None,
    port: str | None = None,
    username: str | None = None,
    password: str | None = None,
    auth_type: str = "basic",
) -> list[HandlerCredential]:
    return [
        HandlerCredential(
            key="host", value=host or os.environ.get("MYSQL_HOST", "localhost")
        ),
        HandlerCredential(
            key="port", value=port or os.environ.get("MYSQL_PORT", "3306")
        ),
        HandlerCredential(
            key="username", value=username or os.environ.get("MYSQL_USER", "root")
        ),
        HandlerCredential(
            key="password", value=password or os.environ.get("MYSQL_PASSWORD", "")
        ),
        HandlerCredential(key="authType", value=auth_type),
    ]


@pytest.fixture(autouse=True)
def require_mysql(mysql_database):  # noqa: ARG001 — pulls in autouse session fixture
    """Skip the whole module when no MySQL is available."""
    if not os.environ.get("MYSQL_HOST"):
        pytest.skip("No MySQL available — set MYSQL_HOST or provide Docker")


class TestHandlerAuth:
    async def test_auth_success(self):
        result = await MySQLAppHandler().test_auth(AuthInput(credentials=_creds()))
        assert result.status == AuthStatus.SUCCESS

    async def test_auth_wrong_password(self):
        result = await MySQLAppHandler().test_auth(
            AuthInput(credentials=_creds(password="definitelywrong"))
        )
        assert result.status == AuthStatus.FAILED

    async def test_auth_unreachable_host(self):
        result = await MySQLAppHandler().test_auth(
            AuthInput(credentials=_creds(host="192.0.2.1", port="3306"))
        )
        assert result.status == AuthStatus.FAILED


class TestHandlerPreflight:
    async def test_preflight_success(self):
        result = await MySQLAppHandler().preflight_check(
            PreflightInput(credentials=_creds())
        )
        assert result.status == PreflightStatus.READY
        check_names = {c.name for c in result.checks}
        assert "auth" in check_names
        assert "connectivity" in check_names
        assert all(c.passed for c in result.checks)

    async def test_preflight_wrong_password(self):
        result = await MySQLAppHandler().preflight_check(
            PreflightInput(credentials=_creds(password="definitelywrong"))
        )
        # Observation window (CNCT-81): overall softened to PARTIAL; the check
        # records the blocking intent. Flip back to NOT_READY at hard-fail.
        assert result.status == PreflightStatus.PARTIAL
        auth_check = next(c for c in result.checks if c.name == "auth")
        assert not auth_check.passed
        assert auth_check.status == PreflightStatus.NOT_READY


class TestHandlerMetadata:
    async def test_metadata_returns_schemas(self):
        result = await MySQLAppHandler().fetch_metadata(
            MetadataInput(credentials=_creds())
        )
        assert len(result.objects) > 0
        schemas = {obj.TABLE_SCHEMA for obj in result.objects}
        # seed.sql creates 'ecommerce' and several other databases
        assert "ecommerce" in schemas

    async def test_metadata_no_host_raises(self):
        with pytest.raises(Exception, match="no host in credentials"):
            await MySQLAppHandler().fetch_metadata(MetadataInput(credentials=[]))
