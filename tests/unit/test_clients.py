from unittest.mock import MagicMock, patch
from urllib.parse import quote_plus

import pytest
from application_sdk.common.error_codes import CommonError

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
            "username": "test_user",
            "password": "test_secret",
            "host": "test-instance.region.rds.amazonaws.com",
            "port": "3306",
            "extra": {
                "database": "test_db",
                "aws_region": "us-east-1",
            },
            "authType": "iam_user",
        }

    @pytest.fixture
    def iam_role_credentials(self):
        """IAM role credentials for testing."""
        return {
            "host": "test-instance.region.rds.amazonaws.com",
            "port": "3306",
            "extra": {
                "database": "test_db",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
                "external_id": "external-id-123",
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
            == "mysql+aiomysql://{username}:{password}@{host}:{port}/{database}"
        )

    @pytest.mark.asyncio
    async def test_load_basic_auth_success(self, basic_credentials):
        """Test successful loading with basic authentication."""
        with patch("sqlalchemy.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_connection = MagicMock()
            mock_engine.connect.return_value.__enter__ = MagicMock(
                return_value=mock_connection
            )
            mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(basic_credentials)

            assert client.credentials == basic_credentials
            mock_create_engine.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_iam_user_auth_success(self, iam_user_credentials):
        """Test successful loading with IAM user authentication."""
        with patch("app.clients.create_aws_session") as mock_create_session, patch(
            "app.clients.get_region_name_from_hostname", return_value="us-east-1"
        ) as mock_get_region, patch(
            "app.clients.create_aws_client"
        ) as mock_create_client, patch(
            "app.clients.generate_aws_rds_token_with_iam_user",
            return_value="test_token",
        ) as mock_get_token, patch("sqlalchemy.create_engine") as mock_create_engine:
            mock_session = MagicMock()
            mock_create_session.return_value = mock_session

            mock_aws_client = MagicMock()
            mock_create_client.return_value = mock_aws_client

            mock_engine = MagicMock()
            mock_connection = MagicMock()
            mock_engine.connect.return_value.__enter__ = MagicMock(
                return_value=mock_connection
            )
            mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(iam_user_credentials)

            assert client.credentials == iam_user_credentials
            mock_create_session.assert_called_once_with(iam_user_credentials)
            mock_get_region.assert_called_once_with(iam_user_credentials["host"])
            mock_get_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_iam_role_auth_success(self, iam_role_credentials):
        """Test successful loading with IAM role authentication."""
        with patch(
            "app.clients.get_region_name_from_hostname", return_value="us-east-1"
        ) as _, patch("boto3.client") as mock_boto_client, patch(
            "app.clients.create_aws_client"
        ) as _, patch(
            "app.clients.generate_aws_rds_token_with_iam_role",
            return_value="test_token",
        ) as mock_get_token, patch("sqlalchemy.create_engine") as mock_create_engine:
            # Mock STS client for assume_role
            mock_sts_client = MagicMock()
            mock_sts_client.assume_role.return_value = {
                "Credentials": {
                    "AccessKeyId": "temp_key",
                    "SecretAccessKey": "temp_secret",
                    "SessionToken": "temp_token",
                }
            }
            mock_boto_client.return_value = mock_sts_client

            # Mock SQLAlchemy engine
            mock_engine = MagicMock()
            mock_connection = MagicMock()
            mock_engine.connect.return_value.__enter__ = MagicMock(
                return_value=mock_connection
            )
            mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_create_engine.return_value = mock_engine

            client = SQLClient()
            await client.load(iam_role_credentials)

            assert client.credentials == iam_role_credentials
            mock_sts_client.assume_role.assert_called_once()
            mock_get_token.assert_called_once()

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

        with pytest.raises(CommonError) as exc_info:
            await client.load(credentials)
        assert str(exc_info.value).startswith(
            "ATLAN-COMMON-400-02: Credentials parse error"
        )

    @pytest.mark.asyncio
    async def test_load_missing_credentials(self):
        """Test loading with missing credentials."""
        client = SQLClient()

        with pytest.raises(ValueError):
            await client.load({})

    def test_get_sqlalchemy_connection_string_basic_auth(self, basic_credentials):
        """Test connection string generation for basic authentication."""
        client = SQLClient()
        client.credentials = basic_credentials
        client.resolved_credentials = basic_credentials

        result = client.get_sqlalchemy_connection_string()
        encoded_password = quote_plus(basic_credentials["password"])

        expected = (
            f"mysql+aiomysql://{basic_credentials['username']}:{encoded_password}@"
            f"{basic_credentials['host']}:{basic_credentials['port']}/"
            f"{basic_credentials['extra']['database']}?connect_timeout=5&charset=utf8mb4"
        )

        assert result == expected

    def test_get_sqlalchemy_connection_string_missing_credentials(self):
        """Test connection string generation when credentials are missing."""
        client = SQLClient()

        with pytest.raises(ValueError, match="is required"):
            client.get_sqlalchemy_connection_string()
