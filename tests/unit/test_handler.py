"""Unit tests for MySQLHandler (v3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pymysql.err as pymysql_err
import pytest
import sqlalchemy.exc as sqlalchemy_exc
from application_sdk.errors import FailureCategory
from application_sdk.handler import (
    AuthInput,
    AuthStatus,
    HandlerCredential,
    MetadataInput,
    PreflightInput,
    PreflightStatus,
)

from app.failures import ConnectionLimitError, transient_failure
from app.handler import MySQLAppHandler, _creds_to_dict


def _wrapped(errno: int, text: str) -> Exception:
    """A driver error as SQLAlchemy delivers it — the real shape the handler sees."""
    return sqlalchemy_exc.OperationalError(
        "SELECT 1", {}, pymysql_err.OperationalError(errno, text)
    )


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

    @pytest.mark.asyncio
    async def test_preflight_auth_failure_short_circuits(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.NOT_READY
        # short-circuit: the advisory tables check never runs
        assert len(result.checks) == 1
        auth_check = result.checks[0]
        assert auth_check.name == "auth"
        assert auth_check.passed is False
        # the typed error rides on the check as a FailureDetails
        assert auth_check.error is not None
        assert auth_check.error.category == FailureCategory.AUTH
        assert auth_check.error.code == "AUTH_MYSQL_PREFLIGHT"
        assert auth_check.error.retryable is False
        assert auth_check.error.suggested_action

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("driver_error", "expected_category"),
        [
            (_wrapped(1040, "Too many connections"), FailureCategory.RATE_LIMITED),
            (
                pymysql_err.OperationalError(2013, "Lost connection to MySQL server"),
                FailureCategory.SOURCE_UNAVAILABLE,
            ),
        ],
    )
    async def test_preflight_transient_auth_failure_is_partial(
        self, handler, valid_creds, driver_error, expected_category
    ):
        """A blip must not block a hard gate: PARTIAL, typed retryable, nothing raised."""
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=driver_error)
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.PARTIAL
        # the advisory check could not run after the blip, so it is absent
        assert len(result.checks) == 1
        auth_check = result.checks[0]
        assert auth_check.name == "auth"
        assert auth_check.passed is False
        assert auth_check.error.category == expected_category
        assert auth_check.error.retryable is True
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
        assert tables_check.error.category == FailureCategory.PERMISSION
        assert tables_check.error.code == "PERMISSION_MYSQL_TABLE_LISTING"
        assert tables_check.error.suggested_action

    @pytest.mark.asyncio
    async def test_preflight_transient_tables_failure_keeps_retryable_leaf(
        self, handler, valid_creds
    ):
        """An advisory blip is PARTIAL either way, but must not be blamed on a grant."""
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(
            side_effect=[
                pd.DataFrame({"1": [1]}),
                _wrapped(1226, "user has exceeded the max_user_connections resource"),
            ]
        )
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.PARTIAL
        tables_check = next(c for c in result.checks if c.name == "connectivity")
        assert tables_check.error.category == FailureCategory.RATE_LIMITED
        assert tables_check.error.retryable is True

    @pytest.mark.asyncio
    async def test_gate_path_input_gives_the_same_verdict(self, handler, valid_creds):
        """The gate builds PreflightInput from contract fields, not from the setup form."""
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(return_value=pd.DataFrame({"count": [42]}))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(
                    credentials=valid_creds,
                    credentials_by_name={},
                    entrypoint="mysql",
                    timeout_seconds=150,
                )
            )

        assert result.status == PreflightStatus.READY
        assert len(result.checks) == 2


class TestTransientClassification:
    """The errno walk, on the shapes the handler actually receives."""

    def test_errno_found_through_a_raise_from_chain(self):
        try:
            try:
                raise pymysql_err.OperationalError(1040, "Too many connections")
            except pymysql_err.OperationalError as inner:
                raise RuntimeError("engine load failed") from inner
        except RuntimeError as outer:
            assert isinstance(transient_failure(outer), ConnectionLimitError)

    def test_definitive_errors_are_not_transient(self):
        assert transient_failure(_wrapped(1045, "Access denied for user")) is None
        assert (
            transient_failure(_wrapped(2003, "Can't connect to MySQL server")) is None
        )
        assert transient_failure(Exception("no errno anywhere")) is None


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
