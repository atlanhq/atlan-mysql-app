from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote_plus

import pytest

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
            "host": "test-instance.region.rds.amazonaws.com",
            "port": "3306",
            "extra": {
                "database": "test_db",
                "username": "db_user",  # Database username (required for IAM user)
                "aws_region": "us-east-1",
            },
            "authType": "iam_user",
        }

    @pytest.fixture
    def iam_role_credentials(self):
        """IAM role credentials for testing."""
        return {
            "username": "db_user",  # MySQL database user
            "host": "test-instance.region.rds.amazonaws.com",
            "port": "3306",
            "extra": {
                "database": "test_db",
                "aws_role_arn": "arn:aws:iam::123456789012:role/test-role",
                "aws_external_id": "external-id-123",
                "aws_region": "us-east-1",
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

    @pytest.mark.asyncio
    async def test_load_iam_user_auth_success(self, iam_user_credentials):
        """Test successful loading with IAM user authentication."""
        with patch.object(
            SQLClient,
            "get_sqlalchemy_connection_string",
            return_value="mysql+aiomysql://user:token@host:3306/db",
        ) as mock_conn_str, patch(
            "sqlalchemy.ext.asyncio.create_async_engine"
        ) as mock_create_engine:
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
            await client.load(iam_user_credentials)

            assert client.credentials == iam_user_credentials
            mock_conn_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_iam_role_auth_success(self, iam_role_credentials):
        """Test successful loading with IAM role authentication."""
        with patch.object(
            SQLClient,
            "get_sqlalchemy_connection_string",
            return_value="mysql+aiomysql://user:token@host:3306/db",
        ) as mock_conn_str, patch(
            "sqlalchemy.ext.asyncio.create_async_engine"
        ) as mock_create_engine:
            # Mock SQLAlchemy async engine
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
            await client.load(iam_role_credentials)

            assert client.credentials == iam_role_credentials
            mock_conn_str.assert_called_once()

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

        with pytest.raises(ValueError) as exc_info:
            await client.load(credentials)
        assert (
            "ATLAN-COMMON-400-03" in str(exc_info.value)
            or "invalid" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_load_missing_credentials(self):
        """Test loading with missing credentials."""
        client = SQLClient()

        with pytest.raises(ValueError):
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
        """Test connection string generation when credentials are missing."""
        client = SQLClient()

        with pytest.raises(ValueError, match="is required"):
            client.get_sqlalchemy_connection_string()

    def test_get_sqlalchemy_connection_string_iam_user(self, iam_user_credentials):
        """Test connection string generation for IAM user authentication."""
        client = SQLClient()
        client.credentials = iam_user_credentials

        with patch.object(client, "get_iam_user_token", return_value="iam_token_12345"):
            result = client.get_sqlalchemy_connection_string()
            encoded_token = quote_plus("iam_token_12345")

            # For IAM user, username should be extra.username (MySQL DB user), not credentials.username (AWS access key)
            expected = (
                f"mysql+aiomysql://{iam_user_credentials['extra']['username']}:{encoded_token}@"
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
