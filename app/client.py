import re
import ssl
from typing import Any, Dict, Optional
from urllib.parse import quote

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient
from application_sdk.clients.sql_errors import (
    SqlClientAuthFailedError,
    SqlClientConfigError,
)
from application_sdk.common.aws_utils import (
    generate_aws_rds_token_with_iam_role,
    generate_aws_rds_token_with_iam_user,
)
from application_sdk.common.aws_utils_errors import AwsAssumeRoleError
from application_sdk.credentials.utils import parse_credentials_extra
from application_sdk.observability.logger_adaptor import get_logger
from app.failures import (
    CredentialFieldMissingError,
    IamTokenGenerationError,
    RegionExtractionError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random

logger = get_logger(__name__)

#: ``authType`` values whose password is a short-lived RDS IAM auth token. The
#: SDK refreshes that token on new connections for exactly these values.
_IAM_AUTH_TYPES = frozenset({"iam_user", "iam_role"})


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
        # TLS (and, for IAM, the clear-password auth plugin) is wired in load(),
        # on an instance copy of DB_CONFIG: this class-level one is shared by
        # every client in the worker and must stay untouched.
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
                    "defaults": {
                        **(self.DB_CONFIG.defaults or {}),
                        "connect_timeout": probe_timeout,
                    }
                },
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
          (if both are provided, they authenticate the STS assume-role call;
          otherwise boto3's default credential chain is used)
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

        # A complete frontend-supplied key pair goes to STS explicitly; without
        # one, the SDK uses boto3's default chain (pod IAM role, etc.). Never
        # stage the keys in os.environ: it is process-global, so concurrent
        # workflows on one worker race on it.
        explicit_keys = (
            {
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key,
            }
            if aws_access_key_id and aws_secret_access_key
            else {}
        )

        try:
            token = generate_aws_rds_token_with_iam_role(
                role_arn=aws_role_arn,
                host=host,
                user=username,
                external_id=external_id,
                port=int(port),
                region=region,
                **explicit_keys,
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

    def get_sqlalchemy_connection_string(self) -> str:
        """Build the SQLAlchemy URL, putting the MySQL user in it for IAM auth.

        Basic auth uses the SDK's builder unchanged. For IAM auth the URL
        carries the MySQL database user and the RDS IAM token as the password:

        - ``iam_user``: the SDK would fill ``{username}`` from
          ``credentials["username"]``, which is the AWS access key ID. The
          MySQL user is ``extra.username``.
        - ``iam_role``: the MySQL user is ``credentials["username"]``.

        The token has to travel in the URL, not ``connect_args``: the SDK's
        token refresh rebuilds this string about every 10 minutes and swaps in
        only the driver arguments the URL changes.

        Called again by that refresh, on a worker thread, for as long as the
        engine lives. It only reads credentials, so it is safe to call
        repeatedly and from any thread; keep it free of ``self.*`` writes.
        """
        if self.credentials.get("authType") not in _IAM_AUTH_TYPES:
            return super().get_sqlalchemy_connection_string()
        if not self.DB_CONFIG:
            raise SqlClientConfigError()

        # Validates every field the URL needs (and generates the token) before
        # any of them is read below; URL-quoted.
        token = self.get_auth_token()

        if self.credentials["authType"] == "iam_user":
            db_user = parse_credentials_extra(self.credentials)["username"]
        else:
            db_user = self.credentials["username"]

        conn_str = self.DB_CONFIG.template.format(
            username=quote(str(db_user), safe=""),
            password=token,
            host=self.credentials["host"],
            port=self.credentials["port"],
        )
        if self.DB_CONFIG.defaults:
            conn_str = self.add_connection_params(conn_str, self.DB_CONFIG.defaults)
        return conn_str

    def _use_connect_args(self, *, iam: bool) -> None:
        """Point this client at TLS ``connect_args``, on an instance copy of DB_CONFIG.

        TLS is on for every auth type (matching the legacy JDBC driver). IAM
        auth also needs ``mysql_clear_password``: RDS reads the token as a
        plain-text password, which TLS protects in transit. Nothing else goes
        in ``connect_args`` — the SDK's token refresh never touches them, so a
        user or password here would never be refreshed.
        """
        if not self.DB_CONFIG:
            return
        connect_args = {
            **self.DB_CONFIG.connect_args,
            "ssl": self._create_ssl_context(),
        }
        if iam:
            connect_args["auth_plugin"] = "mysql_clear_password"
        else:
            connect_args.pop("auth_plugin", None)
        # Shallow is enough: only connect_args changes, and it is a fresh dict.
        self.DB_CONFIG = self.DB_CONFIG.model_copy(
            update={"connect_args": connect_args}
        )

    async def load(self, credentials: Dict[str, Any]) -> None:
        """Create the engine through the SDK, for every auth type.

        For IAM auth the SDK also installs its RDS IAM token refresh: once the
        token in the URL is 10 minutes old, the next new connection rebuilds
        it on a worker thread, so an STS call never runs on the event loop.
        """
        auth_type = str(credentials.get("authType", "basic")).lower()

        if auth_type in _IAM_AUTH_TYPES:
            if credentials.get("authType") != auth_type:
                # The SDK matches authType exactly when it builds the token
                # and decides whether to refresh it.
                credentials = {**credentials, "authType": auth_type}
            self._use_connect_args(iam=True)
            try:
                await super().load(credentials)
            except AwsAssumeRoleError as e:
                # Defense-in-depth: get_iam_role_token() already types STS
                # rejections, at load time and on every later refresh. Any that
                # escapes is translated here so the SDK auth-cache prime
                # classifier routes it to AuthError.
                raise IamTokenGenerationError(
                    message="AWS IAM role authentication failed — could not assume the configured role",
                    failure_reason="assume_role_denied",
                    cause=e,
                ) from e
            return

        # Basic auth: TLS on by default (matching legacy JDBC driver behavior).
        self._use_connect_args(iam=False)

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
