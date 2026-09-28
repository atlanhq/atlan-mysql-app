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
from application_sdk.execution.heartbeat import run_in_thread
from application_sdk.observability.logger_adaptor import get_logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import retry_if_exception_type

# The connection logic both clients share lives once, beside the handler's own
# client; this worker client keeps only what depends on its async base class.
from atlan_mysql_api.client import (
    CONNECTION_DEFAULTS,
    REQUIRED_FIELDS,
    cold_cache_retry,
    create_ssl_context,
    extract_region_from_hostname,
    flatten_basic_credentials,
    iam_connect_args,
    iam_db_username,
    iam_engine_url,
    iam_role_fields,
    iam_user_fields,
    log_iam_role_fields,
    log_iam_user_fields,
    require_iam_role_fields,
    require_iam_user_fields,
    require_token,
    sts_explicit_keys,
    token_refresher,
    with_connect_timeout,
)
from atlan_mysql_api.failures import (
    EngineCreationError,
    IamTokenGenerationError,
)

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
        required=list(REQUIRED_FIELDS),
        defaults=dict(CONNECTION_DEFAULTS),
        # SSL will be enabled in load() method using SSL context (like IAM auth)
        # This avoids class-level initialization issues and allows proper SSL context creation
        connect_args={},
    )

    def __init__(self, *args: Any, probe_timeout: Optional[int] = None, **kwargs: Any):
        """Optionally bound this client's connect attempt.

        ``probe_timeout`` is seconds, and only the preflight gate passes it:
        the gate hands the handler a *remaining* budget, and a connect attempt
        that can outlive it makes the gate's deadline decorative. The override
        lands on an instance-level copy of ``DB_CONFIG`` because the class-level
        one is shared by every client in the worker — mutating it in place would
        hand one probe's deadline to unrelated extraction connections.
        """
        super().__init__(*args, **kwargs)
        if probe_timeout is not None and self.DB_CONFIG is not None:
            # Shallow, with a fresh `defaults` dict: that is the only mapping
            # this override touches, and a deep copy would have to clone
            # `connect_args`, which load() populates with an ssl.SSLContext —
            # not a deep-copyable object.
            self.DB_CONFIG = self.DB_CONFIG.model_copy(
                update={
                    "defaults": with_connect_timeout(
                        self.DB_CONFIG.defaults, probe_timeout
                    )
                },
            )

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """SSL context without certificate verification — see ``create_ssl_context``."""
        return create_ssl_context()

    def _extract_region_from_hostname(self, host: Optional[str]) -> Optional[str]:
        """AWS region from an RDS hostname — see ``extract_region_from_hostname``."""
        return extract_region_from_hostname(host)

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
        fields = iam_user_fields(self.credentials)
        log_iam_user_fields(logger, fields)
        require_iam_user_fields(fields)

        try:
            token = generate_aws_rds_token_with_iam_user(
                aws_access_key_id=fields.aws_access_key_id,
                aws_secret_access_key=fields.aws_secret_access_key,
                host=fields.host,
                user=fields.user,  # MySQL DB user
                port=int(fields.port),
                region=fields.region,
            )
        except Exception as e:
            raise IamTokenGenerationError(
                failure_reason="token_generation_failed", cause=e
            ) from e

        return require_token(token, logger)

    def get_iam_role_token(self) -> str:
        """Get an IAM role token for AWS RDS MySQL authentication.

        For MySQL IAM role authentication:
        - credentials["username"] contains the MySQL database user
        - extra["aws_role_arn"] contains the AWS role ARN
        - extra["aws_external_id"] contains optional external ID
        - extra["aws_access_key_id"] and extra["aws_secret_access_key"] are optional
          (if both are provided, they authenticate the STS assume-role call;
          otherwise boto3's default credential chain is used)
        - Database is optional for MySQL (unlike other databases)

        Returns:
            str: A temporary authentication token for database access.

        Raises:
            CommonError: If required credentials (aws_role_arn) are missing.
        """
        fields = iam_role_fields(self.credentials)
        log_iam_role_fields(logger, fields)
        require_iam_role_fields(fields)
        explicit_keys = sts_explicit_keys(fields)

        try:
            token = generate_aws_rds_token_with_iam_role(
                role_arn=fields.aws_role_arn,
                host=fields.host,
                user=fields.user,
                external_id=fields.external_id,
                port=int(fields.port),
                region=fields.region,
                **explicit_keys,
            )
            return require_token(token, logger)
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
            ssl_context = create_ssl_context()

            # Temporarily add SSL context to DB_CONFIG.connect_args
            # Base class will use this when creating the engine
            if self.DB_CONFIG:
                self.DB_CONFIG.connect_args["ssl"] = ssl_context

            # SDR / agent mode: agent_json uses "basic.username" / "basic.password" dot
            # notation. Flatten them to top-level so the base class finds username/password.
            credentials = flatten_basic_credentials(credentials)

            # Use base class - it will use the modified DB_CONFIG.connect_args.
            # The base class wraps every failed connection attempt in
            # SqlClientAuthFailedError, so that is what the cold-cache retry
            # (see cold_cache_retry) counts.
            @cold_cache_retry(retry_if_exception_type(SqlClientAuthFailedError))
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
        # Get raw IAM token (not URL-encoded). boto3 (in get_iam_*_token) is
        # synchronous, so run it in the SDK's blocking-thread pool to keep the
        # activity's auto-heartbeat alive while STS/RDS is contacted.
        if auth_type == "iam_user":
            raw_token = await run_in_thread(self.get_iam_user_token)
        else:  # iam_role
            raw_token = await run_in_thread(self.get_iam_role_token)

        username = iam_db_username(credentials, auth_type)
        engine_url = iam_engine_url(
            "mysql+aiomysql",
            credentials,
            self.DB_CONFIG.defaults if self.DB_CONFIG else None,
        )
        connect_args = iam_connect_args(
            self.DB_CONFIG.connect_args if self.DB_CONFIG else None,
            username,
            raw_token,
        )

        self.engine = create_async_engine(
            engine_url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )

        if not self.engine:
            raise EngineCreationError()

        # Register event listener as additional safety to ensure token is injected
        # This ensures fresh tokens on each connection (tokens expire)
        get_token = (
            self.get_iam_user_token
            if auth_type == "iam_user"
            else self.get_iam_role_token
        )
        event.listens_for(self.engine.sync_engine, "do_connect")(
            token_refresher(get_token, logger)
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
