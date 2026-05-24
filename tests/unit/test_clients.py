import ssl
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote_plus

import pytest
from application_sdk.clients.sql_errors import (
    MissingSqlParamError,
    SqlClientAuthFailedError,
    SqlClientConfigError,
    SqlCredentialsParseError,
)
from application_sdk.common.error_codes import ClientError

from app.clients import SQLClient


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

        assert (
            call_count == 5
        ), f"Expected exactly 5 attempts (tenacity max) before propagating, got {call_count}"

    @pytest.mark.asyncio
    async def test_load_iam_user_auth_success(self, iam_user_credentials):
        """Test successful loading with IAM user authentication."""
        with (
            patch(
                "app.clients.generate_aws_rds_token_with_iam_user",
                return_value="mock_token_12345",
            ) as mock_token,
            patch("app.clients.create_async_engine") as mock_create_engine,
            patch("sqlalchemy.event.listens_for") as mock_listens_for,
        ):
            mock_engine = MagicMock()
            mock_connection = AsyncMock()
            # Mock async context manager for engine.connect()
            mock_connection_context = AsyncMock()
            mock_connection_context.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_connection_context.__aexit__ = AsyncMock(return_value=None)
            # connect() is a regular method that returns an async context manager
            mock_engine.connect.return_value = mock_connection_context
            mock_sync_engine = MagicMock()
            mock_engine.sync_engine = mock_sync_engine  # For event listener
            mock_engine.dispose = AsyncMock()
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(iam_user_credentials)

            assert client.credentials == iam_user_credentials
            mock_token.assert_called_once()
            mock_create_engine.assert_called_once()
            # Verify event listener was registered
            mock_listens_for.assert_called()

    @pytest.mark.asyncio
    async def test_load_iam_role_auth_success(self, iam_role_credentials):
        """Test successful loading with IAM role authentication."""
        with (
            patch("boto3.Session") as mock_boto3_session,
            patch("app.clients.create_async_engine") as mock_create_engine,
            patch("sqlalchemy.event.listens_for") as mock_listens_for,
            patch(
                "application_sdk.common.aws_utils.create_aws_client"
            ) as mock_create_client,
        ):
            # Mock STS assume_role response
            mock_sts_client = MagicMock()
            mock_sts_client.assume_role.return_value = {
                "Credentials": {
                    "AccessKeyId": "temp_key",
                    "SecretAccessKey": "temp_secret",
                    "SessionToken": "temp_token",
                }
            }

            # Mock boto3.Session().client("sts")
            mock_session_instance = MagicMock()
            mock_session_instance.client.return_value = mock_sts_client
            mock_boto3_session.return_value = mock_session_instance

            # Mock RDS client for token generation
            mock_rds_client = MagicMock()
            mock_rds_client.generate_db_auth_token.return_value = "mock_token_67890"
            mock_create_client.return_value = mock_rds_client

            # Mock SQLAlchemy async engine
            mock_engine = MagicMock()
            mock_connection = AsyncMock()
            # Mock async context manager for engine.connect()
            mock_connection_context = AsyncMock()
            mock_connection_context.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_connection_context.__aexit__ = AsyncMock(return_value=None)
            # connect() is a regular method that returns an async context manager
            mock_engine.connect.return_value = mock_connection_context
            mock_sync_engine = MagicMock()
            mock_engine.sync_engine = mock_sync_engine  # For event listener
            mock_engine.dispose = AsyncMock()
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(iam_role_credentials)

            assert client.credentials == iam_role_credentials
            mock_boto3_session.assert_called()
            mock_create_engine.assert_called_once()
            # Verify event listener was registered
            mock_listens_for.assert_called()

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

        # SDK v3.12+ wraps the missing-credentials failure in
        # ``SqlClientAuthFailedError`` (cause=``SqlCredentialsParseError``
        # or ``SqlClientConfigError``); accept the legacy ValueError /
        # ClientError too so this test survives across SDK versions.
        with pytest.raises((
            ValueError,
            ClientError,
            SqlClientConfigError,
            SqlCredentialsParseError,
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
        """Test connection string generation for IAM user authentication.

        Note: get_sqlalchemy_connection_string() is not used for IAM auth in production
        (we create the engine directly in load()). This test verifies the base class
        behavior, which uses extra.username (DB user) as the username in the connection string.
        """
        client = SQLClient()
        client.credentials = iam_user_credentials

        with patch.object(client, "get_iam_user_token", return_value="iam_token_12345"):
            result = client.get_sqlalchemy_connection_string()
            encoded_token = quote_plus("iam_token_12345")

            # Base class uses credentials["username"] (AWS access key) in the template.
            # In production, IAM auth uses load() which creates engine directly, not this method.
            expected = (
                f"mysql+aiomysql://{iam_user_credentials['username']}:{encoded_token}@"
                f"{iam_user_credentials['host']}:{iam_user_credentials['port']}?connect_timeout=5&charset=utf8mb4"
            )

            assert result == expected

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

        with patch(
            "app.clients.generate_aws_rds_token_with_iam_user",
            return_value="mock_iam_token",
        ) as mock_gen:
            token = client.get_iam_user_token()
            assert token == "mock_iam_token"
            mock_gen.assert_called_once()

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
