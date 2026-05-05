import os
import re
import ssl
from typing import Any, Dict, Optional

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient
from application_sdk.common.aws_utils import (
    generate_aws_rds_token_with_iam_role,
    generate_aws_rds_token_with_iam_user,
)
from application_sdk.common.error_codes import CommonError
from application_sdk.credentials.utils import parse_credentials_extra
from application_sdk.observability.logger_adaptor import get_logger
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

logger = get_logger(__name__)


class SQLClient(AsyncBaseSQLClient):
    """
    This client handles connection string generation based on authentication
    type and manages database connectivity using SQLAlchemy.

    Supports multiple authentication methods:
    - Basic: Username/password authentication
    - IAM User: AWS IAM user authentication using access key/secret
    - IAM Role: AWS IAM role authentication using role ARN

    Note: Database name is optional in MySQL connections. The connection
    template does not include a database, allowing connections without a
    default database, which is compatible with MySQL's behavior and matches
    legacy connector behavior.
    """

    DB_CONFIG: Optional[DatabaseConfig] = DatabaseConfig(
        template="mysql+aiomysql://{username}:{password}@{host}:{port}",
        required=["username", "password", "host", "port"],
        defaults={
            "connect_timeout": 5,
            "charset": "utf8mb4",
        },
        # SSL will be enabled in load() method using SSL context (like IAM auth)
        # This avoids class-level initialization issues and allows proper SSL context creation
        connect_args={},
    )

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """
        Create SSL context without certificate verification for RDS compatibility.

        RDS IAM auth and servers with --require_secure_transport=ON require SSL
        but may have self-signed certificates. This context disables verification
        to allow connections while still using encrypted transport.

        Returns:
            ssl.SSLContext: SSL context configured for RDS compatibility
        """
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _extract_region_from_hostname(self, host: Optional[str]) -> Optional[str]:
        """Extract AWS region from RDS hostname.

        RDS hostname pattern: [identifier].[unique-id].[region].rds.amazonaws.com
        Example: dsp-prd-mysql-analytics.c7y4kcieagzd.ap-south-1.rds.amazonaws.com -> ap-south-1

        Args:
            host: RDS hostname

        Returns:
            Extracted region or None if pattern doesn't match
        """
        if not host:
            return None

        match = re.search(r"\.([a-z0-9-]+)\.rds\.amazonaws\.com", host)
        if match:
            return match.group(1)
        return None

    def get_iam_user_token(self) -> str:
        """Get an IAM user token for AWS RDS MySQL authentication.

        For MySQL IAM user authentication:
        - credentials["username"] contains AWS access key ID (or extra.iam_user.aws_access_key_id)
        - credentials["password"] contains AWS secret access key (or extra.iam_user.aws_secret_access_key)
        - extra["username"] or extra.iam_user["username"] contains the MySQL database user
        - Database is optional for MySQL (unlike other databases)

        Returns:
            str: A temporary authentication token for database access.

        Raises:
            CommonError: If required credentials are missing.
        """
        extra = parse_credentials_extra(self.credentials)

        # Legacy marketplace (nestedValue: false): username=access_key, password=secret_key
        # New PKL form: aws_access_key_id / aws_secret_access_key at top level
        aws_access_key_id = self.credentials.get(
            "aws_access_key_id"
        ) or self.credentials.get("username")
        aws_secret_access_key = self.credentials.get(
            "aws_secret_access_key"
        ) or self.credentials.get("password")
        # MySQL DB user: new PKL form uses db_username, legacy uses extra.username
        user = self.credentials.get("db_username") or extra.get("username")
        host = self.credentials.get("host")
        port = self.credentials.get("port")

        region = self._extract_region_from_hostname(host)

        logger.info(
            f"IAM User Auth - Access Key: {aws_access_key_id[:10] if aws_access_key_id else None}..., "
            f"Host: {host}, Port: {port}, Region: {region}, MySQL User: {user}"
        )

        if not aws_access_key_id:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: username (AWS access key ID) is required for IAM user authentication"
            )
        if not aws_secret_access_key:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: password (AWS secret access key) is required for IAM user authentication"
            )
        if not user:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: extra.username (MySQL database user) is required for IAM user authentication"
            )
        if not host:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: host is required for IAM user authentication"
            )
        if not port:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: port is required for IAM user authentication"
            )
        if not region:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: region is required for IAM user authentication. "
                f"Region could not be extracted from hostname '{host}'. "
                f"Please ensure the hostname follows the RDS pattern: [identifier].[region].rds.amazonaws.com"
            )

        try:
            token = generate_aws_rds_token_with_iam_user(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                host=host,
                user=user,  # MySQL DB user
                port=int(port),
                region=region,
            )
            if not token:
                raise CommonError(
                    f"{CommonError.CREDENTIALS_PARSE_ERROR}: Failed to generate IAM token - token is empty"
                )
            logger.info(f"IAM token generated successfully (length: {len(token)})")
            return token
        except Exception as e:
            logger.error(f"Failed to generate IAM user token: {str(e)}")
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: Failed to generate IAM token: {str(e)}"
            )

    def get_iam_role_token(self) -> str:
        """Get an IAM role token for AWS RDS MySQL authentication.

        For MySQL IAM role authentication:
        - credentials["username"] contains the MySQL database user
        - extra["aws_role_arn"] contains the AWS role ARN
        - extra["aws_external_id"] contains optional external ID
        - extra["aws_access_key_id"] and extra["aws_secret_access_key"] are optional
          (if provided, sets environment variables for default credential chain)
        - Database is optional for MySQL (unlike other databases)

        Returns:
            str: A temporary authentication token for database access.

        Raises:
            CommonError: If required credentials (aws_role_arn) are missing.
        """
        extra = parse_credentials_extra(self.credentials)
        # New PKL form puts aws_role_arn at top level; legacy uses extra.aws_role_arn
        aws_role_arn = extra.get("aws_role_arn") or self.credentials.get("aws_role_arn")
        external_id = (
            extra.get("aws_external_id")
            or self.credentials.get("aws_external_id")
            or None
        )
        # AWS credentials optional — new PKL uses top-level, legacy uses extra.*
        aws_access_key_id = extra.get("aws_access_key_id") or self.credentials.get(
            "aws_access_key_id"
        )
        aws_secret_access_key = extra.get(
            "aws_secret_access_key"
        ) or self.credentials.get("aws_secret_access_key")
        username = self.credentials.get(
            "username"
        )  # MySQL DB user (correct in both old and new)
        host = self.credentials.get("host")
        port = self.credentials.get("port")
        region = self._extract_region_from_hostname(host)

        logger.info(
            f"IAM Role Auth - Role ARN: {aws_role_arn}, Host: {host}, Port: {port}, "
            f"Region: {region}, MySQL User: {username}, External ID: {external_id}"
        )

        if not aws_role_arn:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: extra.aws_role_arn is required for IAM role authentication"
            )
        if not username:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: username (MySQL database user) is required for IAM role authentication"
            )
        if not host:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: host is required for IAM role authentication"
            )
        if not port:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: port is required for IAM role authentication"
            )
        if not region:
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: region is required for IAM role authentication. "
                f"Region could not be extracted from hostname '{host}'. "
                f"Please ensure the hostname follows the RDS pattern: [identifier].[region].rds.amazonaws.com"
            )

        # Set environment variables from frontend credentials if provided
        # This allows SDK's generate_aws_rds_token_with_iam_role to use default credential chain
        # This matches how other apps (Glue, Postgres) handle credentials
        old_env = {}
        if aws_access_key_id and aws_secret_access_key:
            old_env["AWS_ACCESS_KEY_ID"] = os.environ.get("AWS_ACCESS_KEY_ID")
            old_env["AWS_SECRET_ACCESS_KEY"] = os.environ.get("AWS_SECRET_ACCESS_KEY")
            os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
            logger.debug(
                "Set AWS credentials in environment for default credential chain"
            )
        else:
            logger.debug(
                "Using default AWS credential chain (environment variables, IAM instance profile, etc.)"
            )

        try:
            # Use SDK function directly - it now correctly handles ExternalId (commit 931c538)
            # SDK function uses boto3's default credential chain, which will pick up our env vars
            token = generate_aws_rds_token_with_iam_role(
                role_arn=aws_role_arn,
                host=host,
                user=username,
                external_id=external_id,
                port=int(port),
                region=region,
            )

            if not token:
                raise CommonError(
                    f"{CommonError.CREDENTIALS_PARSE_ERROR}: Failed to generate IAM token - token is empty"
                )
            logger.info(f"IAM token generated successfully (length: {len(token)})")
            return token
        finally:
            # Restore original environment variables if we set them
            if aws_access_key_id and aws_secret_access_key:
                old_access_key = old_env.get("AWS_ACCESS_KEY_ID")
                old_secret_key = old_env.get("AWS_SECRET_ACCESS_KEY")
                if old_access_key is not None:
                    os.environ["AWS_ACCESS_KEY_ID"] = old_access_key
                else:
                    os.environ.pop("AWS_ACCESS_KEY_ID", None)
                if old_secret_key is not None:
                    os.environ["AWS_SECRET_ACCESS_KEY"] = old_secret_key
                else:
                    os.environ.pop("AWS_SECRET_ACCESS_KEY", None)

    async def load(self, credentials: Dict[str, Any]) -> None:
        """Override load to handle IAM authentication.

        For IAM authentication, we create the engine directly similar to Redshift,
        ensuring the IAM token is properly passed to the underlying driver.
        """
        self.credentials = credentials
        auth_type = credentials.get("authType", "basic").lower()

        if auth_type in ("iam_user", "iam_role"):
            # For IAM auth, use event listener pattern to inject token at connection time
            # This is the recommended approach for SQLAlchemy async engines with IAM auth

            # Get raw IAM token (not URL-encoded)
            if auth_type == "iam_user":
                raw_token = self.get_iam_user_token()
            else:  # iam_role
                raw_token = self.get_iam_role_token()

            # Determine username based on auth type
            extra = parse_credentials_extra(credentials)
            if auth_type == "iam_user":
                username = extra.get("username")
                if not username:
                    raise ValueError(
                        "extra.username (MySQL database user) is required for IAM user authentication"
                    )
            else:  # iam_role
                username = credentials.get("username")
                if not username:
                    raise ValueError(
                        "username (MySQL database user) is required for IAM role authentication"
                    )

            host = credentials.get("host")
            port = credentials.get("port")
            if not host or not port:
                raise ValueError("host and port are required")

            # Build query parameters
            query_params: Dict[str, str] = {}
            if self.DB_CONFIG and self.DB_CONFIG.defaults:
                for key, value in self.DB_CONFIG.defaults.items():
                    if value is not None:
                        query_params[key] = str(value)

            url_kwargs = {
                "drivername": "mysql+aiomysql",
                "host": host,
                "port": int(port),
            }
            if query_params:
                url_kwargs["query"] = query_params

            engine_url = URL.create(**url_kwargs)

            # Create SSL context without certificate verification for RDS IAM auth
            ssl_context = self._create_ssl_context()

            # Create async engine with all auth parameters in connect_args
            connect_args = dict(self.DB_CONFIG.connect_args if self.DB_CONFIG else {})
            connect_args["user"] = username
            connect_args["password"] = raw_token
            connect_args["auth_plugin"] = "mysql_clear_password"
            connect_args["ssl"] = ssl_context

            self.engine = create_async_engine(
                str(engine_url),
                connect_args=connect_args,
                pool_pre_ping=True,
            )

            if not self.engine:
                raise ValueError("Failed to create async engine")

            # Register event listener as additional safety to ensure token is injected
            # This ensures fresh tokens on each connection (tokens expire)
            @event.listens_for(self.engine.sync_engine, "do_connect")
            def provide_token(dialect, conn_rec, cargs, cparams):
                """Event listener to inject/refresh IAM token before connecting."""
                # Get fresh token (tokens expire, so regenerate for each connection)
                if auth_type == "iam_user":
                    token = self.get_iam_user_token()
                else:  # iam_role
                    token = self.get_iam_role_token()

                # Inject token into connection parameters
                cparams["password"] = token
                logger.debug(
                    f"Event listener: Refreshed IAM token (length: {len(token)}) for connection"
                )

            # Test connection briefly to validate credentials
            async with self.engine.connect() as _:
                pass  # Connection test successful

            # Don't store persistent connection (base class sets this to None)
            # self.connection is managed by the base class
        else:
            # For basic auth, enable SSL by default (matching legacy JDBC driver behavior)
            # Create SSL context and modify DB_CONFIG.connect_args before calling base class
            ssl_context = self._create_ssl_context()

            # Temporarily add SSL context to DB_CONFIG.connect_args
            # Base class will use this when creating the engine
            if self.DB_CONFIG:
                self.DB_CONFIG.connect_args["ssl"] = ssl_context

            # SDR / agent mode: agent_json uses "basic.username" / "basic.password" dot
            # notation. Flatten them to top-level so the base class finds username/password.
            if "basic.username" in credentials or "basic.password" in credentials:
                credentials = {
                    **credentials,
                    "username": credentials.get("basic.username")
                    or credentials.get("username"),
                    "password": credentials.get("basic.password")
                    or credentials.get("password"),
                }

            # Use base class - it will use the modified DB_CONFIG.connect_args
            await super().load(credentials)
