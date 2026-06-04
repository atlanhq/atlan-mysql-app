import os
import re
import ssl
from typing import Any, Dict, Optional

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient
from application_sdk.clients.sql_errors import SqlClientAuthFailedError
from application_sdk.common.aws_utils import (
    generate_aws_rds_token_with_iam_role,
    generate_aws_rds_token_with_iam_user,
)
from application_sdk.common.aws_utils_errors import AwsAssumeRoleError
from application_sdk.credentials.utils import parse_credentials_extra
from application_sdk.observability.logger_adaptor import get_logger
from app.failures import (
    CredentialFieldMissingError,
    EngineCreationError,
    IamTokenGenerationError,
    RegionExtractionError,
)
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random

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

        # Legacy marketplace mapping (matches PKL form using extraFields):
        #   credentials.username        = AWS access key ID
        #   credentials.password        = AWS secret access key
        #   credentials.extra.username  = MySQL database user
        aws_access_key_id = self.credentials.get("username")
        aws_secret_access_key = self.credentials.get("password")
        user = extra.get("username")
        host = self.credentials.get("host")
        port = self.credentials.get("port")

        region = self._extract_region_from_hostname(host)

        logger.info(
            "IAM user auth — access_key_id=%.10s..., host=%s, port=%s, region=%s, user=%s",
            aws_access_key_id or "None",
            host,
            port,
            region,
            user,
        )

        if not aws_access_key_id:
            raise CredentialFieldMissingError(
                message="username (AWS access key ID) is required for IAM user authentication",
                field="username",
            )
        if not aws_secret_access_key:
            raise CredentialFieldMissingError(
                message="password (AWS secret access key) is required for IAM user authentication",
                field="password",
            )
        if not user:
            raise CredentialFieldMissingError(
                message="extra.username (MySQL database user) is required for IAM user authentication",
                field="extra.username",
            )
        if not host:
            raise CredentialFieldMissingError(
                message="host is required for IAM user authentication",
                field="host",
            )
        if not port:
            raise CredentialFieldMissingError(
                message="port is required for IAM user authentication",
                field="port",
            )
        if not region:
            raise RegionExtractionError(
                message="Region could not be extracted from RDS hostname; expected [identifier].[region].rds.amazonaws.com",
                field="host",
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
        except Exception as e:
            raise IamTokenGenerationError(
                failure_reason="token_generation_failed", cause=e
            ) from e

        if not token:
            raise IamTokenGenerationError(
                message="AWS RDS IAM token generation returned an empty token",
                failure_reason="empty_token",
            )
        logger.info("IAM token generated successfully (length: %d)", len(token))
        return token

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
        # Legacy marketplace mapping (matches PKL form using extraFields):
        #   credentials.username             = MySQL database user
        #   credentials.extra.aws_role_arn   = IAM role ARN
        #   credentials.extra.aws_external_id (optional) = STS external ID
        #   credentials.extra.aws_access_key_id / aws_secret_access_key (optional)
        aws_role_arn = extra.get("aws_role_arn")
        external_id = extra.get("aws_external_id") or None
        aws_access_key_id = extra.get("aws_access_key_id")
        aws_secret_access_key = extra.get("aws_secret_access_key")
        username = self.credentials.get("username")  # MySQL DB user
        host = self.credentials.get("host")
        port = self.credentials.get("port")
        region = self._extract_region_from_hostname(host)

        logger.info(
            "IAM role auth — role_arn=%s, host=%s, port=%s, region=%s, user=%s, has_external_id=%s",
            aws_role_arn,
            host,
            port,
            region,
            username,
            bool(external_id),
        )

        if not aws_role_arn:
            raise CredentialFieldMissingError(
                message="extra.aws_role_arn is required for IAM role authentication",
                field="extra.aws_role_arn",
            )
        if not username:
            raise CredentialFieldMissingError(
                message="username (MySQL database user) is required for IAM role authentication",
                field="username",
            )
        if not host:
            raise CredentialFieldMissingError(
                message="host is required for IAM role authentication",
                field="host",
            )
        if not port:
            raise CredentialFieldMissingError(
                message="port is required for IAM role authentication",
                field="port",
            )
        if not region:
            raise RegionExtractionError(
                message="Region could not be extracted from RDS hostname; expected [identifier].[region].rds.amazonaws.com",
                field="host",
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
                raise IamTokenGenerationError(
                    message="AWS RDS IAM token generation returned an empty token",
                    failure_reason="empty_token",
                )
            logger.info("IAM token generated successfully (length: %d)", len(token))
            return token
        except AwsAssumeRoleError as e:
            # STS rejected the assume-role call — re-raise with a message that
            # contains "authentication failed" so the SDK's auth-cache prime
            # classifier (_classify_prime_failure auth_msg_hints) routes this
            # to AuthError rather than the InternalError fallback bucket.
            raise IamTokenGenerationError(
                message="AWS IAM role authentication failed — could not assume the configured role",
                failure_reason="assume_role_denied",
                cause=e,
            ) from e
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
            try:
                await self._load_iam(credentials, auth_type)
            except IamTokenGenerationError:
                raise
            except AwsAssumeRoleError as e:
                # Defense-in-depth: any AwsAssumeRoleError that escapes the
                # inner catch in get_iam_role_token() (or the do_connect event
                # listener) is translated here so the SDK auth-cache prime
                # classifier (_classify_prime_failure auth_msg_hints) routes
                # this to AuthError rather than the InternalError fallback.
                raise IamTokenGenerationError(
                    message="AWS IAM role authentication failed — could not assume the configured role",
                    failure_reason="assume_role_denied",
                    cause=e,
                ) from e
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

            # Use base class - it will use the modified DB_CONFIG.connect_args.
            # Tenacity retry for MySQL 8 caching_sha2_password cold-cache:
            # the server-side cache can require several failed connection
            # attempts before it is warm enough for a subsequent attempt to
            # take the fast path and succeed. Each failed attempt progressively
            # populates the cache. Jitter spreads retries to avoid thundering-
            # herd when multiple workers start simultaneously on a cold server.
            @retry(
                retry=retry_if_exception_type(SqlClientAuthFailedError),
                stop=stop_after_attempt(5),
                wait=wait_random(min=0, max=0.5),
                reraise=True,
            )
            async def _load_with_retry():
                if self.engine:
                    await self.engine.dispose()
                await super(SQLClient, self).load(credentials)

            await _load_with_retry()

    async def _load_iam(self, credentials: Dict[str, Any], auth_type: str) -> None:
        """Load engine for IAM (user or role) authentication.

        Extracted from ``load`` so the outer caller can wrap this entire
        path in a single ``try/except AwsAssumeRoleError`` — STS failures
        raised from any inner call site (initial token gen, do_connect
        event listener, connection test) are translated to
        ``IamTokenGenerationError`` before they leave the mysql app
        boundary.
        """
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
                raise CredentialFieldMissingError(
                    message="extra.username (MySQL database user) is required for IAM user authentication",
                    field="extra.username",
                )
        else:  # iam_role
            username = credentials.get("username")
            if not username:
                raise CredentialFieldMissingError(
                    message="username (MySQL database user) is required for IAM role authentication",
                    field="username",
                )

        host = credentials.get("host")
        port = credentials.get("port")
        if not host or not port:
            raise CredentialFieldMissingError(
                message="host and port are required for IAM authentication",
                field="host",
            )

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
            raise EngineCreationError()

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
                "IAM token refreshed for connection (length: %d)", len(token)
            )

        # Test connection briefly to validate credentials
        try:
            async with self.engine.connect() as _:
                pass  # Connection test successful
        except IamTokenGenerationError:
            raise  # already typed from event listener; propagate as-is
        except AwsAssumeRoleError:
            raise  # let load()'s outer wrapper translate it
        except Exception as e:
            # The token was generated successfully, so a connection-test
            # failure here is almost always MySQL rejecting the IAM token
            # (e.g. "Access denied" or "Lost connection" from auth-plugin
            # negotiation).  Re-raise with "authentication failed" in the
            # message so the SDK auth-cache prime classifier routes it to
            # AuthError rather than DependencyUnavailableError.
            raise IamTokenGenerationError(
                message="AWS IAM authentication failed — MySQL rejected the connection after token injection",
                failure_reason="connection_rejected",
                cause=e,
            ) from e
