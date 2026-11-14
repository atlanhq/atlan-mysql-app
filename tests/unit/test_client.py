import os
import ssl
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote_plus

import application_sdk.clients.sql as sdk_sql
import pymysql
import pytest
import sqlalchemy.ext.asyncio as sa_asyncio
from application_sdk.clients.sql_errors import (
    MissingSqlParamError,
    SqlClientAuthFailedError,
    SqlClientConfigError,
    SqlClientSourceUnavailableError,
    SqlCredentialsParseError,
)
from application_sdk.common.aws_utils_errors import AwsAssumeRoleError
from application_sdk.common.error_codes import ClientError
from sqlalchemy import event
from sqlalchemy.engine import make_url

from app.client import SQLClient
from app.failures import IamTokenGenerationError
from tests.unit.loop_probe import LoopProbe


class TestMySQLClient:
    """Test suite for MySQL SQLClient."""

    @pytest.fixture
    def basic_credentials(self):
        """Basic credentials for testing."""
        return {
            "username": "test_user",
            "password": "test@pass!123",
            "host": "localhost",
            "port": "3306",
            "extra": {"database": "test_db"},
            "authType": "basic",
        }

    @pytest.fixture
    def iam_user_credentials(self):
        """IAM user credentials for testing."""
        return {
            "username": "aws_access_key",  # AWS access key
            "password": "aws_secret_key",  # AWS secret key
            "host": "test-instance.us-east-1.rds.amazonaws.com",  # Valid AWS region format
            "port": "3306",
            "region": "us-east-1",  # Region in credentials (not just extra)
            "extra": {
                "database": "test_db",
                "username": "db_user",  # Database username (required for IAM user)
            },
            "authType": "iam_user",
        }

    @pytest.fixture
    def iam_role_credentials(self):
        """IAM role credentials for testing."""
        return {
            "username": "db_user",  # MySQL database user
            "host": "test-instance.us-east-1.rds.amazonaws.com",  # Valid AWS region format
            "port": "3306",
            "region": "us-east-1",  # Region in credentials (required for IAM role)
            "extra": {
                "database": "test_db",
                "aws_role_arn": "arn:aws:iam::123456789012:role/test-role",
                "aws_external_id": "external-id-123",
            },
            "authType": "iam_role",
        }

    def test_mysql_client_initialization(self):
        """Test SQLClient initialization."""
        client = SQLClient()
        assert client is not None
        assert hasattr(client, "DB_CONFIG")
        assert client.DB_CONFIG is not None
        assert (
            client.DB_CONFIG.template
            == "mysql+aiomysql://{username}:{password}@{host}:{port}"
        )
        # Database is optional, not in required fields
        assert "database" not in client.DB_CONFIG.required

    @pytest.mark.asyncio
    async def test_load_basic_auth_success(self, basic_credentials):
        """Test successful loading with basic authentication."""
        with patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_connection = AsyncMock()
            # Mock async context manager for engine.connect()
            mock_connection_context = AsyncMock()
            mock_connection_context.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_connection_context.__aexit__ = AsyncMock(return_value=None)
            mock_engine.connect.return_value = mock_connection_context
            mock_engine.dispose = AsyncMock()
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(basic_credentials)

            assert client.credentials == basic_credentials
            mock_create_engine.assert_called_once()
            # Basic-auth path must enable SSL (matches legacy JDBC driver
            # behavior) — connect_args carries the ssl context through to
            # the base class's engine creation.
            assert client.DB_CONFIG is not None
            ssl_arg = client.DB_CONFIG.connect_args.get("ssl")
            assert isinstance(ssl_arg, ssl.SSLContext)
            assert ssl_arg.verify_mode is ssl.CERT_NONE

    @pytest.mark.parametrize("succeed_on_attempt", [1, 2, 3, 4, 5])
    @pytest.mark.asyncio
    async def test_load_basic_auth_retries_on_cold_cache(
        self, basic_credentials, succeed_on_attempt
    ):
        """Basic auth retries up to 5 times (tenacity) on SqlClientAuthFailedError.

        MySQL 8's caching_sha2_password server-side cache can require several
        failed connection attempts before it is warm enough for a subsequent
        connection to take the fast path and succeed.
        """
        call_count = 0

        async def _flaky_load(_creds):
            nonlocal call_count
            call_count += 1
            if call_count < succeed_on_attempt:
                raise SqlClientAuthFailedError(
                    message="SQL client authentication failed",
                    failure_reason="OperationalError(1045, Access denied)",
                )

        with (
            patch.object(SQLClient.__bases__[0], "load", side_effect=_flaky_load),
            patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_engine_factory,
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            mock_engine = MagicMock()
            mock_engine.dispose = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            client = SQLClient()
            client.engine = mock_engine
            await client.load(basic_credentials)

        assert call_count == succeed_on_attempt

    @pytest.mark.asyncio
    async def test_load_basic_auth_stops_after_max_attempts(self, basic_credentials):
        """If all 5 attempts fail, SqlClientAuthFailedError propagates — no infinite loop."""
        call_count = 0

        async def _always_fail(_creds):
            nonlocal call_count
            call_count += 1
            raise SqlClientAuthFailedError(
                message="SQL client authentication failed",
                failure_reason="OperationalError(1045, Access denied)",
            )

        with (
            patch.object(SQLClient.__bases__[0], "load", side_effect=_always_fail),
            patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_engine_factory,
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            mock_engine = MagicMock()
            mock_engine.dispose = AsyncMock()
            mock_engine_factory.return_value = mock_engine

            client = SQLClient()
            client.engine = mock_engine
            with pytest.raises(SqlClientAuthFailedError):
                await client.load(basic_credentials)

        assert call_count == 5, (
            f"Expected exactly 5 attempts (tenacity max) before propagating, got {call_count}"
        )

    @staticmethod
    def _mock_engine() -> MagicMock:
        """An async-engine double whose connect() is a no-op context manager."""
        mock_engine = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect.return_value = ctx
        mock_engine.dispose = AsyncMock()
        return mock_engine

    @pytest.mark.parametrize(
        ("auth_fixture", "token_fn", "db_user"),
        [
            ("iam_user_credentials", "generate_aws_rds_token_with_iam_user", "db_user"),
            ("iam_role_credentials", "generate_aws_rds_token_with_iam_role", "db_user"),
        ],
        ids=["iam_user", "iam_role"],
    )
    @pytest.mark.asyncio
    async def test_load_iam_goes_through_the_sdk_with_the_token_in_the_url(
        self, request, auth_fixture, token_fn, db_user
    ):
        """IAM auth builds its engine through the SDK's load(): the MySQL user
        and the token travel in the URL, and connect_args carry only TLS and the
        clear-password plugin — nothing the SDK's token refresh would skip."""
        credentials = request.getfixturevalue(auth_fixture)
        with (
            patch(f"app.client.{token_fn}", return_value=TOKEN_0) as mock_token,
            patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create_engine,
        ):
            mock_create_engine.return_value = self._mock_engine()

            client = SQLClient()
            await client.load(credentials)

        assert client.credentials == credentials
        mock_token.assert_called_once()
        mock_create_engine.assert_called_once()
        url = make_url(mock_create_engine.call_args.args[0])
        assert url.username == db_user
        assert url.password == TOKEN_0
        connect_args = mock_create_engine.call_args.kwargs["connect_args"]
        assert connect_args["auth_plugin"] == "mysql_clear_password"
        assert isinstance(connect_args["ssl"], ssl.SSLContext)
        assert "password" not in connect_args
        assert "user" not in connect_args
        # The class-level DB_CONFIG is shared by every client in the worker.
        assert SQLClient.DB_CONFIG.connect_args == {}

    @pytest.mark.asyncio
    async def test_load_iam_role_translates_assume_role_error(
        self, iam_role_credentials
    ):
        """AwsAssumeRoleError raised during initial token gen surfaces as
        IamTokenGenerationError (AuthError) with a message that the SDK
        auth-cache prime classifier routes to AuthError."""
        with patch(
            "app.client.generate_aws_rds_token_with_iam_role",
            side_effect=AwsAssumeRoleError(cause=Exception("STS denied")),
        ):
            client = SQLClient()
            with pytest.raises(IamTokenGenerationError) as exc_info:
                await client.load(iam_role_credentials)
            assert "authentication failed" in str(exc_info.value).lower()
            assert exc_info.value.failure_reason == "assume_role_denied"

    @pytest.mark.asyncio
    async def test_load_iam_role_passes_through_existing_iam_token_error(
        self, iam_role_credentials
    ):
        """An IamTokenGenerationError raised by inner code is re-raised
        unchanged — no double-wrapping or message mutation."""
        sentinel = IamTokenGenerationError(
            message="inner-typed error",
            failure_reason="empty_token",
        )
        with patch.object(SQLClient, "get_iam_role_token", side_effect=sentinel):
            client = SQLClient()
            with pytest.raises(IamTokenGenerationError) as exc_info:
                await client.load(iam_role_credentials)
            assert exc_info.value is sentinel

    @pytest.mark.asyncio
    async def test_load_invalid_auth_type(self):
        """Test loading with invalid authentication type."""
        credentials = {
            "authType": "invalid",
            "username": "test_user",
            "password": "test_pass",
            "host": "localhost",
            "port": "3306",
            "extra": {"database": "test_db"},
        }

        client = SQLClient()

        # SDK v3.12+ wraps invalid-authType in
        # ``SqlClientAuthFailedError(cause=SqlCredentialsParseError(field="authType", ...))``;
        # earlier SDKs raised ValueError / ClientError directly. Accept
        # either shape and walk the exception cause chain to assert the
        # failure is specifically about the bad authType.
        with pytest.raises((
            ValueError,
            ClientError,
            SqlCredentialsParseError,
            SqlClientAuthFailedError,
        )) as exc_info:
            await client.load(credentials)

        def _chain_includes(exc: BaseException, needles: tuple[str, ...]) -> bool:
            current: BaseException | None = exc
            while current is not None:
                blob = f"{type(current).__name__} {current!s} {vars(current)}".lower()
                if any(n.lower() in blob for n in needles):
                    return True
                current = current.__cause__
            return False

        assert _chain_includes(
            exc_info.value, ("ATLAN-COMMON-400-03", "invalid", "authtype")
        )

    @pytest.mark.asyncio
    async def test_load_missing_credentials(self):
        """Test loading with missing credentials."""
        client = SQLClient()

        # Newer SDKs raise the typed ``MissingSqlParamError`` unwrapped;
        # SDK v3.12+ before that wrapped it in ``SqlClientAuthFailedError``;
        # older SDKs raised ValueError / ClientError. Accept all so this test
        # survives across SDK versions.
        with pytest.raises((
            ValueError,
            ClientError,
            SqlClientConfigError,
            SqlCredentialsParseError,
            MissingSqlParamError,
            SqlClientAuthFailedError,
        )):
            await client.load({})

    def test_get_sqlalchemy_connection_string_basic_auth(self, basic_credentials):
        """Test connection string generation for basic authentication.

        Note: Database is optional and not included in connection string even if provided.
        """
        client = SQLClient()
        client.credentials = basic_credentials
        client.resolved_credentials = basic_credentials

        result = client.get_sqlalchemy_connection_string()
        encoded_password = quote_plus(basic_credentials["password"])

        expected = (
            f"mysql+aiomysql://{basic_credentials['username']}:{encoded_password}@"
            f"{basic_credentials['host']}:{basic_credentials['port']}?connect_timeout=5&charset=utf8mb4"
        )

        assert result == expected

    def test_get_sqlalchemy_connection_string_without_database(self):
        """Test connection string generation without database (optional)."""
        credentials = {
            "username": "test_user",
            "password": "test@pass!123",
            "host": "localhost",
            "port": "3306",
            "extra": {},  # No database
            "authType": "basic",
        }
        client = SQLClient()
        client.credentials = credentials
        client.resolved_credentials = credentials

        result = client.get_sqlalchemy_connection_string()
        encoded_password = quote_plus(credentials["password"])

        expected = (
            f"mysql+aiomysql://{credentials['username']}:{encoded_password}@"
            f"{credentials['host']}:{credentials['port']}?connect_timeout=5&charset=utf8mb4"
        )

        assert result == expected

    def test_get_sqlalchemy_connection_string_missing_credentials(self):
        """Test connection string generation when credentials are missing.

        SDK v3.12+ raises ``SqlClientConfigError`` / ``MissingSqlParamError``
        instead of a bare ``ValueError``; accept either.
        """
        client = SQLClient()

        with pytest.raises((ValueError, SqlClientConfigError, MissingSqlParamError)):
            client.get_sqlalchemy_connection_string()

    def test_get_sqlalchemy_connection_string_iam_user(self, iam_user_credentials):
        """For IAM user auth the URL user is extra.username (the MySQL user),
        not credentials.username (the AWS access key ID)."""
        client = SQLClient()
        client.credentials = iam_user_credentials

        with patch.object(client, "get_iam_user_token", return_value="iam_token_12345"):
            result = client.get_sqlalchemy_connection_string()
            encoded_token = quote_plus("iam_token_12345")

            expected = (
                f"mysql+aiomysql://{iam_user_credentials['extra']['username']}:{encoded_token}@"
                f"{iam_user_credentials['host']}:{iam_user_credentials['port']}?connect_timeout=5&charset=utf8mb4"
            )

            assert result == expected
            assert iam_user_credentials["username"] not in result

    def test_get_sqlalchemy_connection_string_iam_quotes_token_and_user(
        self, iam_role_credentials
    ):
        """A real RDS token is a presigned URL; it and the user must survive
        the round trip through the SQLAlchemy URL unchanged."""
        client = SQLClient()
        client.credentials = {**iam_role_credentials, "username": "db:user@x"}

        with patch.object(client, "get_iam_role_token", return_value=TOKEN_0):
            url = make_url(client.get_sqlalchemy_connection_string())

        assert url.username == "db:user@x"
        assert url.password == TOKEN_0
        assert url.host == iam_role_credentials["host"]

    def test_get_sqlalchemy_connection_string_iam_role(self, iam_role_credentials):
        """Test connection string generation for IAM role authentication."""
        client = SQLClient()
        client.credentials = iam_role_credentials

        with patch.object(client, "get_iam_role_token", return_value="iam_token_67890"):
            result = client.get_sqlalchemy_connection_string()
            encoded_token = quote_plus("iam_token_67890")

            # For IAM role, username should be credentials.username (MySQL DB user)
            expected = (
                f"mysql+aiomysql://{iam_role_credentials['username']}:{encoded_token}@"
                f"{iam_role_credentials['host']}:{iam_role_credentials['port']}?connect_timeout=5&charset=utf8mb4"
            )

            assert result == expected

    def test_extract_region_from_hostname(self):
        """Test AWS region extraction from RDS hostname."""
        client = SQLClient()
        assert (
            client._extract_region_from_hostname(
                "test.abc123.us-east-1.rds.amazonaws.com"
            )
            == "us-east-1"
        )
        assert (
            client._extract_region_from_hostname("db.xyz.ap-south-1.rds.amazonaws.com")
            == "ap-south-1"
        )
        assert client._extract_region_from_hostname("localhost") is None
        assert client._extract_region_from_hostname(None) is None
        assert client._extract_region_from_hostname("") is None

    def test_create_ssl_context(self):
        """Test SSL context creation for RDS."""
        client = SQLClient()
        ctx = client._create_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False
        # RDS/self-signed compatibility: verification must be disabled (not
        # just hostname checking) or connections still traverse TLS.
        assert ctx.verify_mode is ssl.CERT_NONE

    def test_get_iam_user_token_success(self):
        """Test successful IAM user token generation."""
        client = SQLClient()
        client.credentials = {
            "username": "aws_access_key",
            "password": "aws_secret_key",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }

        with (
            patch(
                "app.client.generate_aws_rds_token_with_iam_user",
                return_value="mock_iam_token",
            ) as mock_gen,
            patch("app.client.logger") as mock_logger,
        ):
            token = client.get_iam_user_token()
            assert token == "mock_iam_token"
            mock_gen.assert_called_once()
            # Secret hygiene: the auth log line must truncate the AWS access
            # key id (via %.10s), never interpolate it in full.
            auth_log_call = mock_logger.info.call_args_list[0]
            rendered = auth_log_call[0][0] % auth_log_call[0][1:]
            assert "aws_access_key" not in rendered
            assert rendered.split("access_key_id=")[1].startswith("aws_access")

    def test_get_iam_user_token_missing_extra_username(self):
        """Test IAM user token generation when extra.username is missing."""
        client = SQLClient()
        client.credentials = {
            "username": "aws_access_key",
            "password": "aws_secret_key",
            "host": "test-host",
            "port": "3306",
            "extra": {},  # Missing username
            "authType": "iam_user",
        }

        with pytest.raises(Exception, match="extra.username.*required"):
            client.get_iam_user_token()

    def test_get_iam_user_token_missing_access_key(self):
        """Test IAM user token generation when access key is missing."""
        client = SQLClient()
        client.credentials = {
            "username": "",
            "password": "secret",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with pytest.raises(Exception):
            client.get_iam_user_token()

    def test_get_iam_user_token_missing_secret_key(self):
        """Test IAM user token generation when secret key is missing."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with pytest.raises(Exception):
            client.get_iam_user_token()

    def test_get_iam_role_token_success(self):
        """Test successful IAM role token generation."""
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "region": "us-east-1",
            "extra": {
                "aws_role_arn": "arn:aws:iam::123456:role/test",
                "aws_external_id": "ext-123",
            },
            "authType": "iam_role",
        }

        with (
            patch("boto3.Session") as mock_session,
            patch(
                "application_sdk.common.aws_utils.create_aws_client"
            ) as mock_create_client,
        ):
            mock_sts = MagicMock()
            mock_sts.assume_role.return_value = {
                "Credentials": {
                    "AccessKeyId": "tmp_key",
                    "SecretAccessKey": "tmp_secret",
                    "SessionToken": "tmp_token",
                }
            }
            mock_session.return_value.client.return_value = mock_sts
            mock_rds = MagicMock()
            mock_rds.generate_db_auth_token.return_value = "role_token"
            mock_create_client.return_value = mock_rds

            token = client.get_iam_role_token()
            assert token == "role_token"

    def test_get_iam_role_token_missing_role_arn(self):
        """Test IAM role token generation when aws_role_arn is missing."""
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test-host",
            "port": "3306",
            "extra": {},  # Missing aws_role_arn
            "authType": "iam_role",
        }

        with pytest.raises(Exception, match="aws_role_arn.*required"):
            client.get_iam_role_token()

    # ------------------------------------------------------------------
    # IAM user token — validation gaps
    # ------------------------------------------------------------------

    def test_get_iam_user_token_missing_host(self):
        """host validation fires before token gen."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "secret",
            "host": "",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with pytest.raises(Exception, match="host.*required"):
            client.get_iam_user_token()

    def test_get_iam_user_token_missing_port(self):
        """port validation fires before token gen."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "secret",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with pytest.raises(Exception, match="port.*required"):
            client.get_iam_user_token()

    def test_get_iam_user_token_non_rds_hostname_raises_region_error(self):
        """Hostnames not matching the [identifier].[region].rds.amazonaws.com
        pattern can't be region-extracted and must be rejected."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "secret",
            "host": "mysql.internal.example.com",  # non-RDS
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with pytest.raises(Exception, match="[Rr]egion"):
            client.get_iam_user_token()

    def test_get_iam_user_token_sdk_exception_translates_to_iam_token_error(self):
        """A generic exception from the SDK token-gen helper is translated
        into IamTokenGenerationError(token_generation_failed)."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "secret",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with patch(
            "app.client.generate_aws_rds_token_with_iam_user",
            side_effect=RuntimeError("boto3 blew up"),
        ):
            with pytest.raises(IamTokenGenerationError) as exc_info:
                client.get_iam_user_token()
            assert exc_info.value.failure_reason == "token_generation_failed"

    def test_get_iam_user_token_empty_token_raises(self):
        """An empty string from the SDK token-gen helper raises
        IamTokenGenerationError(empty_token) rather than returning."""
        client = SQLClient()
        client.credentials = {
            "username": "access_key",
            "password": "secret",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"username": "db_user"},
            "authType": "iam_user",
        }
        with patch("app.client.generate_aws_rds_token_with_iam_user", return_value=""):
            with pytest.raises(IamTokenGenerationError) as exc_info:
                client.get_iam_user_token()
            assert exc_info.value.failure_reason == "empty_token"

    # ------------------------------------------------------------------
    # IAM role token — validation gaps
    # ------------------------------------------------------------------

    def test_get_iam_role_token_missing_username(self):
        client = SQLClient()
        client.credentials = {
            "username": "",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r"},
            "authType": "iam_role",
        }
        with pytest.raises(Exception, match="username.*required"):
            client.get_iam_role_token()

    def test_get_iam_role_token_missing_host(self):
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "",
            "port": "3306",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r"},
            "authType": "iam_role",
        }
        with pytest.raises(Exception, match="host.*required"):
            client.get_iam_role_token()

    def test_get_iam_role_token_missing_port(self):
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r"},
            "authType": "iam_role",
        }
        with pytest.raises(Exception, match="port.*required"):
            client.get_iam_role_token()

    def test_get_iam_role_token_non_rds_hostname_raises_region_error(self):
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "mysql.internal.example.com",  # non-RDS
            "port": "3306",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r"},
            "authType": "iam_role",
        }
        with pytest.raises(Exception, match="[Rr]egion"):
            client.get_iam_role_token()

    def test_get_iam_role_token_empty_token_raises(self):
        """SDK helper returning empty string raises empty_token error."""
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r"},
            "authType": "iam_role",
        }
        with patch("app.client.generate_aws_rds_token_with_iam_role", return_value=""):
            with pytest.raises(IamTokenGenerationError) as exc_info:
                client.get_iam_role_token()
            assert exc_info.value.failure_reason == "empty_token"

    def test_get_iam_role_token_passes_keys_explicitly(self, monkeypatch):
        """When extra carries aws_access_key_id / aws_secret_access_key, they
        are passed to the SDK explicitly — the process-global AWS_* env vars
        are never touched, so concurrent workflows cannot race on them."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "prior_access")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "prior_secret")

        observed = {}

        def fake_token(**kwargs):
            observed["kwargs"] = kwargs
            observed["access_key_during_call"] = os.environ.get("AWS_ACCESS_KEY_ID")
            observed["secret_key_during_call"] = os.environ.get("AWS_SECRET_ACCESS_KEY")
            return "tok"

        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {
                "aws_role_arn": "arn:aws:iam::123:role/r",
                "aws_access_key_id": "override_access",
                "aws_secret_access_key": "override_secret",
            },
            "authType": "iam_role",
        }

        with patch(
            "app.client.generate_aws_rds_token_with_iam_role", side_effect=fake_token
        ):
            assert client.get_iam_role_token() == "tok"

        assert observed["kwargs"]["aws_access_key_id"] == "override_access"
        assert observed["kwargs"]["aws_secret_access_key"] == "override_secret"
        # The environment is untouched during and after the call
        assert observed["access_key_during_call"] == "prior_access"
        assert observed["secret_key_during_call"] == "prior_secret"
        assert os.environ.get("AWS_ACCESS_KEY_ID") == "prior_access"
        assert os.environ.get("AWS_SECRET_ACCESS_KEY") == "prior_secret"

    @pytest.mark.parametrize(
        "extra_keys",
        [{}, {"aws_access_key_id": "override_access"}],
        ids=["no_keys", "half_pair"],
    )
    def test_get_iam_role_token_without_full_pair_uses_default_chain(self, extra_keys):
        """No keys, or only half a pair, passes no explicit keys — the SDK
        falls back to boto3's default credential chain."""
        client = SQLClient()
        client.credentials = {
            "username": "db_user",
            "host": "test.abc123.us-east-1.rds.amazonaws.com",
            "port": "3306",
            "extra": {"aws_role_arn": "arn:aws:iam::123:role/r", **extra_keys},
            "authType": "iam_role",
        }
        with patch(
            "app.client.generate_aws_rds_token_with_iam_role", return_value="tok"
        ) as mock_gen:
            assert client.get_iam_role_token() == "tok"
        kwargs = mock_gen.call_args.kwargs
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs

    # ------------------------------------------------------------------
    # load() — connection-test failure path
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("driver_error", "expected", "retryable"),
        [
            (
                pymysql.err.OperationalError(
                    1045,
                    "Access denied for user 'db_user'@'10.0.0.1' (using password: YES)",
                ),
                SqlClientAuthFailedError,
                False,
            ),
            (
                pymysql.err.OperationalError(
                    2003,
                    "Can't connect to MySQL server on 'test-instance' ([Errno 111] Connection refused)",
                ),
                SqlClientSourceUnavailableError,
                True,
            ),
        ],
        ids=["access_denied", "unreachable"],
    )
    @pytest.mark.asyncio
    async def test_load_iam_connection_test_failure_uses_the_sdk_classifier(
        self, iam_role_credentials, driver_error, expected, retryable
    ):
        """A failed connection test is typed by the SDK, as it is for basic
        auth. MySQL rejecting the token stays a non-retryable auth failure;
        an unreachable server is no longer misreported as one, and is retried.
        """
        with (
            patch(
                "app.client.generate_aws_rds_token_with_iam_role",
                return_value=TOKEN_0,
            ),
            patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_create_engine,
        ):
            mock_engine = self._mock_engine()
            mock_engine.connect.side_effect = driver_error
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            with pytest.raises(expected) as exc_info:
                await client.load(iam_role_credentials)

        assert exc_info.value.effective_retryable is retryable


# ----------------------------------------------------------------------
# The SDK's RDS IAM token refresh, on the app's own async engine
# ----------------------------------------------------------------------

#: Shaped like a real RDS auth token: a presigned query string with characters
#: that must survive URL quoting.
TOKEN_0 = (
    "test-instance.us-east-1.rds.amazonaws.com:3306/?Action=connect"
    "&DBUser=db_user&X-Amz-Credential=AKIA%2F20261109&X-Amz-Signature=a+b/0"
)
TOKEN_1 = TOKEN_0.replace("a+b/0", "c+d/1")


class _StopConnect(Exception):
    """Raised by the recorder so no connect ever reaches a socket."""


class _Ping:
    """Stands in for load()'s connection test."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


async def _load_on_a_real_engine(
    client: SQLClient, credentials: dict, *, token_age: float = 0.0
) -> Any:
    """Run the real load() on a real aiomysql engine; return that engine.

    Only load()'s connection test is stubbed. ``token_age`` backdates load()'s
    token issue time; the refresh measures it against the real clock, so an
    age past 10 minutes makes the next new connection rebuild the token.
    """
    real_create = sa_asyncio.create_async_engine
    engines: list[Any] = []

    def _create(url: str, **kwargs: Any) -> Any:
        real = real_create(url, **kwargs)
        engines.append(real)
        wrapper = MagicMock()
        wrapper.sync_engine = real.sync_engine
        wrapper.connect = MagicMock(return_value=_Ping())
        wrapper.dispose = AsyncMock()
        return wrapper

    aged = SimpleNamespace(monotonic=lambda: time.monotonic() - token_age)
    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", side_effect=_create),
        patch.object(sdk_sql, "time", aged),
    ):
        await client.load(credentials)
    return engines[0]


def _record_connect_params(sync_engine: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def _record(dialect, conn_rec, cargs, cparams) -> None:
        seen.append(dict(cparams))
        raise _StopConnect

    event.listen(sync_engine, "do_connect", _record)
    return seen


IAM_ROLE_CREDENTIALS = {
    "username": "db_user",
    "host": "test-instance.us-east-1.rds.amazonaws.com",
    "port": "3306",
    "extra": {"aws_role_arn": "arn:aws:iam::123456789012:role/test-role"},
    "authType": "iam_role",
}


@pytest.mark.asyncio
async def test_an_aged_iam_token_is_rebuilt_off_the_event_loop() -> None:
    """A new connection after the token aged gets a fresh one, built on a
    worker thread: the STS AssumeRole never holds the event loop."""
    probe = LoopProbe()
    calls: list[dict[str, Any]] = []

    def _sts_token(**kwargs: Any) -> str:
        calls.append(kwargs)
        if len(calls) == 1:
            return TOKEN_0  # load(): run_in_thread, outside the probe
        probe.block()  # stands in for the STS AssumeRole on refresh
        return TOKEN_1

    client = SQLClient()
    with patch(
        "app.client.generate_aws_rds_token_with_iam_role", side_effect=_sts_token
    ):
        engine = await _load_on_a_real_engine(
            client, dict(IAM_ROLE_CREDENTIALS), token_age=11 * 60
        )
        seen = _record_connect_params(engine.sync_engine)

        async def _connect() -> None:
            with pytest.raises(_StopConnect):
                async with engine.connect():
                    pass

        await probe.run(_connect)
    await engine.dispose()

    probe.assert_loop_stayed_free("refreshing the RDS IAM token on an app connect")
    assert len(calls) == 2
    assert seen[0]["password"] == TOKEN_1
    assert seen[0]["user"] == "db_user"
    assert seen[0]["auth_plugin"] == "mysql_clear_password"
    assert isinstance(seen[0]["ssl"], ssl.SSLContext)


@pytest.mark.asyncio
async def test_a_fresh_iam_token_is_reused_without_calling_sts() -> None:
    """Unlike the old per-connect listener, a token under 10 minutes old is
    reused: no STS call on the connect path at all."""
    client = SQLClient()
    with patch(
        "app.client.generate_aws_rds_token_with_iam_role", return_value=TOKEN_0
    ) as mock_token:
        engine = await _load_on_a_real_engine(client, dict(IAM_ROLE_CREDENTIALS))
        seen = _record_connect_params(engine.sync_engine)
        with pytest.raises(_StopConnect):
            async with engine.connect():
                pass
    await engine.dispose()

    assert mock_token.call_count == 1
    assert seen[0]["password"] == TOKEN_0


@pytest.mark.asyncio
async def test_an_sts_rejection_on_refresh_is_typed_as_iam_auth_failure() -> None:
    """An STS failure now surfaces from a later connect, not load(); it still
    arrives as IamTokenGenerationError(assume_role_denied)."""
    calls = {"n": 0}

    def _sts_token(**kwargs: Any) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return TOKEN_0
        raise AwsAssumeRoleError(cause=Exception("STS denied on refresh"))

    client = SQLClient()
    with patch(
        "app.client.generate_aws_rds_token_with_iam_role", side_effect=_sts_token
    ):
        engine = await _load_on_a_real_engine(
            client, dict(IAM_ROLE_CREDENTIALS), token_age=11 * 60
        )
        with pytest.raises(IamTokenGenerationError) as exc_info:
            async with engine.connect():
                pass
    await engine.dispose()

    assert exc_info.value.failure_reason == "assume_role_denied"
    assert "authentication failed" in str(exc_info.value).lower()
