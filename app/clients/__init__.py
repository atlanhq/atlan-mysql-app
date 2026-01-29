from typing import Any, Dict, Optional

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient
from application_sdk.common.aws_utils import generate_aws_rds_token_with_iam_user
from application_sdk.common.error_codes import CommonError
from application_sdk.common.utils import parse_credentials_extra
from application_sdk.observability.logger_adaptor import get_logger

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
    )

    def get_iam_user_token(self) -> str:
        """Get an IAM user token for AWS RDS MySQL authentication.

        For MySQL IAM user authentication:
        - credentials["username"] contains AWS access key ID
        - credentials["password"] contains AWS secret access key
        - extra["username"] contains the MySQL database user
        - Database is optional for MySQL (unlike other databases)

        Returns:
            str: A temporary authentication token for database access.

        Raises:
            CommonError: If required credentials are missing.
        """
        extra = parse_credentials_extra(self.credentials)
        aws_access_key_id = self.credentials.get("username")
        aws_secret_access_key = self.credentials.get("password")
        user = extra.get("username")  # MySQL DB user, not AWS access key
        host = self.credentials.get("host")
        port = self.credentials.get("port")
        region = self.credentials.get("region")

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
        - Database is optional for MySQL (unlike other databases)

        Returns:
            str: A temporary authentication token for database access.

        Raises:
            CommonError: If required credentials (aws_role_arn) are missing.
        """
        extra = parse_credentials_extra(self.credentials)
        aws_role_arn = extra.get("aws_role_arn")
        # Convert empty string to None (AWS requires ExternalId to be at least 2 chars if provided)
        external_id = extra.get("aws_external_id") or None
        # AWS credentials are optional - if not provided, use default credential chain (like Glue)
        aws_access_key_id = extra.get("aws_access_key_id")
        aws_secret_access_key = extra.get("aws_secret_access_key")
        username = self.credentials.get("username")  # MySQL DB user
        host = self.credentials.get("host")
        port = self.credentials.get("port")
        region = self.credentials.get("region")

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
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: region is required for IAM role authentication"
            )

        from application_sdk.constants import AWS_SESSION_NAME

        try:
            # Use boto3 directly to assume role (matching Glue pattern)
            # This avoids SDK bug where ExternalId="" is always passed to AWS
            import boto3
            from application_sdk.common.aws_utils import create_aws_client

            logger.info(f"Assuming IAM role: {aws_role_arn}")
            # Create base session (uses default credential chain or explicit credentials if provided)
            # This matches Glue's approach: boto3.Session(region_name=self.region)
            if aws_access_key_id and aws_secret_access_key:
                # Use explicit credentials if provided
                base_session = boto3.Session(
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=region,
                )
                logger.debug("Using explicit AWS credentials for role assumption")
            else:
                # Use default credential chain (environment variables, IAM instance profile, etc.)
                base_session = boto3.Session(region_name=region)
                logger.debug("Using default AWS credential chain for role assumption")

            sts_client = base_session.client("sts")

            assume_role_kwargs = {
                "RoleArn": aws_role_arn,
                "RoleSessionName": AWS_SESSION_NAME,
                "DurationSeconds": 3600,
            }

            # Only add ExternalId if it has a value (AWS rejects empty strings)
            if external_id:
                assume_role_kwargs["ExternalId"] = external_id

            assumed_role = sts_client.assume_role(**assume_role_kwargs)
            logger.info(f"Successfully assumed role: {aws_role_arn}")

            temp_credentials = assumed_role["Credentials"]
            rds_client = create_aws_client(
                service="rds",
                region=region,
                temp_credentials=temp_credentials,
            )

            token = rds_client.generate_db_auth_token(
                DBHostname=host,
                Port=int(port),
                DBUsername=username,
                Region=region,
            )

            if not token:
                raise CommonError(
                    f"{CommonError.CREDENTIALS_PARSE_ERROR}: Failed to generate IAM token - token is empty"
                )
            logger.info(f"IAM token generated successfully (length: {len(token)})")
            return token
        except Exception as e:
            logger.error(f"Failed to generate IAM role token: {str(e)}")
            raise CommonError(
                f"{CommonError.CREDENTIALS_PARSE_ERROR}: Failed to generate IAM token: {str(e)}"
            )

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
            import ssl

            from sqlalchemy import event
            from sqlalchemy.engine import URL
            from sqlalchemy.ext.asyncio import create_async_engine

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
            # RDS IAM auth requires SSL but may have self-signed certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

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
            # For basic auth, use base class implementation
            await super().load(credentials)
