"""Unit tests for MySQLHandler (v3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from application_sdk.errors import FailureCategory
from application_sdk.handler import (
    AuthInput,
    AuthStatus,
    HandlerCredential,
    MetadataInput,
    PreflightInput,
    PreflightStatus,
)

from app.handler import MySQLAppHandler, _creds_to_dict


class TestCredsToDict:
    """Test HandlerCredential → dict conversion."""

    def test_flat_credentials(self):
        creds = [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
        ]
        result = _creds_to_dict(creds)
        assert result["host"] == "localhost"
        assert result["port"] == "3306"
        assert result["username"] == "root"
        assert result["password"] == "secret"

    def test_extra_fields_nested(self):
        creds = [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="extra.database", value="mydb"),
            HandlerCredential(key="extra.charset", value="utf8mb4"),
        ]
        result = _creds_to_dict(creds)
        assert result["host"] == "localhost"
        assert result["extra"]["database"] == "mydb"
        assert result["extra"]["charset"] == "utf8mb4"

    def test_empty_credentials(self):
        result = _creds_to_dict([])
        assert result == {}


class TestMySQLHandlerAuth:
    """Test auth endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_auth_success(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(return_value=pd.DataFrame({"1": [1]}))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.SUCCESS
        assert "successful" in result.message.lower()

    @pytest.mark.asyncio
    async def test_auth_failure(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.FAILED
        assert result.message == "Authentication failed"

    @pytest.mark.asyncio
    async def test_auth_empty_credentials(self, handler):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=ValueError("Missing credentials"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=[]))
        assert result.status == AuthStatus.FAILED


class TestMySQLHandlerPreflight:
    """Test preflight check endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_preflight_success(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(return_value=pd.DataFrame({"count": [42]}))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.READY
        assert len(result.checks) == 2
        assert all(c.passed for c in result.checks)
        # every check carries its own verdict (soft-fail contract)
        assert all(c.status == PreflightStatus.READY for c in result.checks)
        # the message reports the actual aggregate count, not the row count
        tables_check = next(c for c in result.checks if c.name == "connectivity")
        assert tables_check.message == "Found 42 accessible tables"

    @pytest.mark.asyncio
    async def test_preflight_auth_failure_short_circuits(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        # Observation window (CNCT-81): a blocking failure returns overall
        # PARTIAL so the run proceeds; the check itself records the blocking
        # intent as NOT_READY. Revert to overall NOT_READY at hard-fail flip.
        assert result.status == PreflightStatus.PARTIAL
        # short-circuit: the advisory tables check never runs
        assert len(result.checks) == 1
        auth_check = result.checks[0]
        assert auth_check.name == "auth"
        assert auth_check.passed is False
        assert auth_check.status == PreflightStatus.NOT_READY
        # the typed error rides on the check as a FailureDetails
        assert auth_check.error is not None
        assert auth_check.error.category == FailureCategory.AUTH
        assert auth_check.error.suggested_action

    @pytest.mark.asyncio
    async def test_preflight_auth_ok_tables_fail_is_partial(self, handler, valid_creds):
        mock_client = AsyncMock()
        # auth query succeeds; the advisory tables query fails
        mock_client.get_results = AsyncMock(
            side_effect=[pd.DataFrame({"1": [1]}), Exception("no SELECT grant")]
        )
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.PARTIAL
        assert len(result.checks) == 2
        assert next(c for c in result.checks if c.name == "auth").passed is True
        tables_check = next(c for c in result.checks if c.name == "connectivity")
        assert tables_check.passed is False
        # advisory by design: stays PARTIAL forever, not just during the window
        assert tables_check.status == PreflightStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_preflight_never_returns_overall_not_ready(
        self, handler, valid_creds
    ):
        # Observation-window invariant: whatever fails, the aggregate must not
        # block the gate. Both checks failing is the worst case.
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status != PreflightStatus.NOT_READY


class TestMySQLHandlerMetadata:
    """Test metadata fetch endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_fetch_metadata_returns_schemas(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(
            return_value=pd.DataFrame({
                "database_name": ["def", "def"],
                "schema_name": ["mydb", "testdb"],
            })
        )
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.fetch_metadata(
                MetadataInput(credentials=valid_creds)
            )

        assert len(result.objects) == 2
        assert result.objects[0].TABLE_SCHEMA == "mydb"
        assert result.objects[1].TABLE_SCHEMA == "testdb"

    @pytest.mark.asyncio
    async def test_fetch_metadata_raises_when_no_host(self, handler):
        """Empty credentials must raise, not silently return empty results.

        This guards against credential-resolution races where fetch_metadata
        is called before credentials are populated — previously this returned
        an empty SqlMetadataOutput which caused blank filter dropdowns in the UI.
        """
        with pytest.raises(Exception, match="no host in credentials"):
            await handler.fetch_metadata(MetadataInput(credentials=[]))
