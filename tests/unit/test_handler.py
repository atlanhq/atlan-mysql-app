"""Unit tests for MySQLHandler (v3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from application_sdk.handler import (
    AuthInput,
    AuthStatus,
    HandlerCredential,
    MetadataInput,
    PreflightInput,
    PreflightStatus,
)

from app.handlers.mysql import MySQLAppHandler as MySQLHandler
from app.handlers.mysql import _creds_to_dict


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
        return MySQLHandler()

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

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.SUCCESS
        assert "successful" in result.message.lower()

    @pytest.mark.asyncio
    async def test_auth_failure(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.FAILED
        assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_auth_empty_credentials(self, handler):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=ValueError("Missing credentials"))
        mock_client.close = AsyncMock()

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=[]))
        assert result.status == AuthStatus.FAILED


class TestMySQLHandlerPreflight:
    """Test preflight check endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLHandler()

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

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.READY
        assert len(result.checks) == 2
        assert all(c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_preflight_auth_failure(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Auth failed"))
        mock_client.close = AsyncMock()

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.NOT_READY


class TestMySQLHandlerMetadata:
    """Test metadata fetch endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLHandler()

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

        with patch("app.handlers.mysql.SQLClient", return_value=mock_client):
            result = await handler.fetch_metadata(
                MetadataInput(credentials=valid_creds)
            )

        assert len(result.objects) == 2
        assert result.objects[0].TABLE_SCHEMA == "mydb"
        assert result.objects[1].TABLE_SCHEMA == "testdb"
