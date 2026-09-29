"""MySQL connection for the handler, and the connection logic the worker shares.

The handler (auth, preflight, metadata) runs in two places: the worker, where
the SDK's preflight gate calls it, and the consolidated API host. The host
installs only ``atlan-application-sdk-api``, so the handler cannot use the
worker's ``app.client.SQLClient`` (built on ``application_sdk``'s
``AsyncBaseSQLClient``). ``MySQLHandlerClient`` is the handler's client on both
surfaces, built on ``application_sdk_api.clients.BaseSQLClient``.

Everything about *how to connect to MySQL* that does not depend on which base
client is underneath lives here once, as module-level helpers, and the worker's
``app.client.SQLClient`` delegates to them: the TLS context, the RDS region
parse, the SDR ``basic.*`` flattening, the IAM credential mapping and its
validation, the IAM engine URL and connect args, the per-connection token
refresh, and the caching_sha2_password cold-cache retry policy.

What is still written twice (the IAM token calls, the engine construction and
the eager connection test) is written twice only because the two base clients
differ — sync versus async engine, ``application_sdk_api.aws`` versus
``application_sdk.common.aws_utils``. Collapsing those needs the SDK to ship
one client for both surfaces.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Optional

from application_sdk_api.aws import create_aws_client, create_aws_session
from application_sdk_api.clients import BaseSQLClient, DatabaseConfig
from application_sdk_api.credentials.utils import parse_credentials_extra
from application_sdk_api.errors import AppError
from application_sdk_api.observability.logger_adaptor import get_logger
from sqlalchemy.engine import URL
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random

from atlan_mysql_api.failures import (
    CredentialFieldMissingError,
    EngineCreationError,
    IamTokenGenerationError,
    RegionExtractionError,
)

logger = get_logger(__name__)

# =============================================================================
# Shared connection logic — the worker's app/client.py delegates to these.
# =============================================================================

#: Credential keys every basic-auth connection needs.
REQUIRED_FIELDS: tuple[str, ...] = ("username", "password", "host", "port")

#: Connection defaults. Neither names a template placeholder, so both reach the
#: URL as query parameters on both clients.
CONNECTION_DEFAULTS: dict[str, Any] = {
    "connect_timeout": 5,
    "charset": "utf8mb4",
}


def aws_session_name() -> str:
    """STS session name for the IAM role path.

    Same env var and default as ``application_sdk.constants.AWS_SESSION_NAME``,
    which the worker's token helper reads; the api package does not carry that
    constant. Read per call, not at import: the host imports this package into
    a process it shares with other apps (P053).
    """
    return os.getenv("AWS_SESSION_NAME", "temp-session")


def with_connect_timeout(
    defaults: Optional[dict[str, Any]], probe_timeout: Optional[int]
) -> dict[str, Any]:
    """``defaults`` with the connect timeout overridden, as a fresh dict.

    Fresh because the class-level ``DB_CONFIG`` is shared by every client in
    the process — mutating it in place would hand one probe's deadline to
    unrelated connections.
    """
    merged = dict(defaults or {})
    if probe_timeout is not None:
        merged["connect_timeout"] = probe_timeout
    return merged


def create_ssl_context() -> ssl.SSLContext:
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


def extract_region_from_hostname(host: Optional[str]) -> Optional[str]:
    """Extract AWS region from RDS hostname.

    RDS hostname pattern: [identifier].[unique-id].[region].rds.amazonaws.com
    Example: example-db.abc123xyz.ap-south-1.rds.amazonaws.com -> ap-south-1

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


def flatten_basic_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    """SDR / agent mode: lift ``basic.username`` / ``basic.password`` to top level.

    agent_json uses dot notation for these, and the connection-string builder
    only reads top-level ``username`` / ``password``.
    """
    if "basic.username" in credentials or "basic.password" in credentials:
        return {
            **credentials,
            "username": credentials.get("basic.username")
            or credentials.get("username"),
            "password": credentials.get("basic.password")
            or credentials.get("password"),
        }
    return credentials


def cold_cache_retry(condition: Any) -> Callable[..., Any]:
    """Tenacity retry for MySQL 8 caching_sha2_password cold-cache.

    The server-side cache can require several failed connection attempts
    before it is warm enough for a subsequent attempt to take the fast path and
    succeed. Each failed attempt progressively populates the cache. Jitter
    spreads retries to avoid thundering-herd when multiple workers start
    simultaneously on a cold server. ``condition`` is which failures count as
    a connection attempt, which differs by base client.
    """
    return retry(
        retry=condition,
        stop=stop_after_attempt(5),
        wait=wait_random(min=0, max=0.5),
        reraise=True,
    )


@dataclass(frozen=True)
class IamUserFields:
    """The IAM-user credential mapping.

    Legacy marketplace mapping (matches PKL form using extraFields):
      credentials.username        = AWS access key ID
      credentials.password        = AWS secret access key
      credentials.extra.username  = MySQL database user
    """

    aws_access_key_id: Any
    aws_secret_access_key: Any
    user: Any
    host: Any
    port: Any
    region: Optional[str]


def iam_user_fields(credentials: dict[str, Any]) -> IamUserFields:
    extra = parse_credentials_extra(credentials)
    host = credentials.get("host")
    return IamUserFields(
        aws_access_key_id=credentials.get("username"),
        aws_secret_access_key=credentials.get("password"),
        user=extra.get("username"),
        host=host,
        port=credentials.get("port"),
        region=extract_region_from_hostname(host),
    )


def log_iam_user_fields(log: Any, fields: IamUserFields) -> None:
    # %.10s: the access key id is truncated, never interpolated in full.
    log.info(
        "IAM user auth — access_key_id=%.10s..., host=%s, port=%s, region=%s, user=%s",
        fields.aws_access_key_id or "None",
        fields.host,
        fields.port,
        fields.region,
        fields.user,
    )


def require_iam_user_fields(fields: IamUserFields) -> None:
    if not fields.aws_access_key_id:
        raise CredentialFieldMissingError(
            message="username (AWS access key ID) is required for IAM user authentication",
            field="username",
        )
    if not fields.aws_secret_access_key:
        raise CredentialFieldMissingError(
            message="password (AWS secret access key) is required for IAM user authentication",
            field="password",
        )
    if not fields.user:
        raise CredentialFieldMissingError(
            message="extra.username (MySQL database user) is required for IAM user authentication",
            field="extra.username",
        )
    if not fields.host:
        raise CredentialFieldMissingError(
            message="host is required for IAM user authentication",
            field="host",
        )
    if not fields.port:
        raise CredentialFieldMissingError(
            message="port is required for IAM user authentication",
            field="port",
        )
    if not fields.region:
        raise RegionExtractionError(
            message="Region could not be extracted from RDS hostname; expected [identifier].[region].rds.amazonaws.com",
            field="host",
        )


@dataclass(frozen=True)
class IamRoleFields:
    """The IAM-role credential mapping.

    Legacy marketplace mapping (matches PKL form using extraFields):
      credentials.username             = MySQL database user
      credentials.extra.aws_role_arn   = IAM role ARN
      credentials.extra.aws_external_id (optional) = STS external ID
      credentials.extra.aws_access_key_id / aws_secret_access_key (optional)
    """

    aws_role_arn: Any
    external_id: Any
    aws_access_key_id: Any
    aws_secret_access_key: Any
    user: Any
    host: Any
    port: Any
    region: Optional[str]


def iam_role_fields(credentials: dict[str, Any]) -> IamRoleFields:
    extra = parse_credentials_extra(credentials)
    host = credentials.get("host")
    return IamRoleFields(
        aws_role_arn=extra.get("aws_role_arn"),
        external_id=extra.get("aws_external_id") or None,
        aws_access_key_id=extra.get("aws_access_key_id"),
        aws_secret_access_key=extra.get("aws_secret_access_key"),
        user=credentials.get("username"),
        host=host,
        port=credentials.get("port"),
        region=extract_region_from_hostname(host),
    )


def log_iam_role_fields(log: Any, fields: IamRoleFields) -> None:
    log.info(
        "IAM role auth — role_arn=%s, host=%s, port=%s, region=%s, user=%s, has_external_id=%s",
        fields.aws_role_arn,
        fields.host,
        fields.port,
        fields.region,
        fields.user,
        bool(fields.external_id),
    )


def require_iam_role_fields(fields: IamRoleFields) -> None:
    if not fields.aws_role_arn:
        raise CredentialFieldMissingError(
            message="extra.aws_role_arn is required for IAM role authentication",
            field="extra.aws_role_arn",
        )
    if not fields.user:
        raise CredentialFieldMissingError(
            message="username (MySQL database user) is required for IAM role authentication",
            field="username",
        )
    if not fields.host:
        raise CredentialFieldMissingError(
            message="host is required for IAM role authentication",
            field="host",
        )
    if not fields.port:
        raise CredentialFieldMissingError(
            message="port is required for IAM role authentication",
            field="port",
        )
    if not fields.region:
        raise RegionExtractionError(
            message="Region could not be extracted from RDS hostname; expected [identifier].[region].rds.amazonaws.com",
            field="host",
        )


def sts_explicit_keys(fields: IamRoleFields) -> dict[str, Any]:
    """The key pair for the STS assume-role call, or ``{}`` for the default chain.

    A complete frontend-supplied key pair goes to STS explicitly; without one,
    boto3's default chain (pod IAM role, etc.) is used. Never stage the keys in
    os.environ: it is process-global, so concurrent callers race on it.
    """
    if fields.aws_access_key_id and fields.aws_secret_access_key:
        return {
            "aws_access_key_id": fields.aws_access_key_id,
            "aws_secret_access_key": fields.aws_secret_access_key,
        }
    return {}


def require_token(token: Optional[str], log: Any) -> str:
    if not token:
        raise IamTokenGenerationError(
            message="AWS RDS IAM token generation returned an empty token",
            failure_reason="empty_token",
        )
    log.info("IAM token generated successfully (length: %d)", len(token))
    return token


def iam_db_username(credentials: dict[str, Any], auth_type: str) -> str:
    """The MySQL database user for an IAM connection, validated."""
    if auth_type == "iam_user":
        username = parse_credentials_extra(credentials).get("username")
        if not username:
            raise CredentialFieldMissingError(
                message="extra.username (MySQL database user) is required for IAM user authentication",
                field="extra.username",
            )
        return username
    username = credentials.get("username")
    if not username:
        raise CredentialFieldMissingError(
            message="username (MySQL database user) is required for IAM role authentication",
            field="username",
        )
    return username


def iam_engine_url(
    drivername: str, credentials: dict[str, Any], defaults: Optional[dict[str, Any]]
) -> str:
    """Engine URL for an IAM connection: host, port and defaults, no userinfo.

    The user and token travel in connect_args instead, so the token never sits
    in a URL string.
    """
    host = credentials.get("host")
    port = credentials.get("port")
    if not host or not port:
        raise CredentialFieldMissingError(
            message="host and port are required for IAM authentication",
            field="host",
        )
    query_params: dict[str, str] = {
        key: str(value) for key, value in (defaults or {}).items() if value is not None
    }
    url_kwargs: dict[str, Any] = {
        "drivername": drivername,
        "host": host,
        "port": int(port),
    }
    if query_params:
        url_kwargs["query"] = query_params
    return str(URL.create(**url_kwargs))


def iam_connect_args(
    base: Optional[dict[str, Any]], username: str, token: str
) -> dict[str, Any]:
    """connect_args carrying the IAM user and token over TLS."""
    connect_args = dict(base or {})
    connect_args["user"] = username
    connect_args["password"] = token
    connect_args["auth_plugin"] = "mysql_clear_password"
    connect_args["ssl"] = create_ssl_context()
    return connect_args


def token_refresher(get_token: Callable[[], str], log: Any) -> Callable[..., None]:
    """A ``do_connect`` listener that injects a fresh IAM token per connection.

    Tokens expire, so every new pooled connection gets its own.
    """

    def provide_token(dialect: Any, conn_rec: Any, cargs: Any, cparams: Any) -> None:
        token = get_token()
        cparams["password"] = token
        log.debug("IAM token refreshed for connection (length: %d)", len(token))

    return provide_token


# =============================================================================
# The handler's client
# =============================================================================

# boto3's STS/RDS calls block, so they run off the event loop — but not on
# asyncio's default executor: on the worker this handler runs inside the
# preflight gate's activity, and Temporal's SDK uses that pool itself (P031).
# The worker's own client uses application_sdk's run_in_thread, which the api
# package does not ship, so the handler's client keeps a small pool of its own.
_IAM_EXECUTOR: ThreadPoolExecutor | None = None
_IAM_EXECUTOR_LOCK = threading.Lock()


def _iam_executor() -> ThreadPoolExecutor:
    global _IAM_EXECUTOR
    if _IAM_EXECUTOR is None:
        with _IAM_EXECUTOR_LOCK:
            if _IAM_EXECUTOR is None:
                _IAM_EXECUTOR = ThreadPoolExecutor(
                    max_workers=4, thread_name_prefix="atlan_mysql_api_iam"
                )
    return _IAM_EXECUTOR


def _is_connection_attempt(exc: BaseException) -> bool:
    """A driver/connect failure, which the cold-cache retry may retry.

    A typed ``AppError`` (a missing field, an absent DB_CONFIG) is decided from
    the credentials alone and no retry can change it.
    """
    return not isinstance(exc, AppError)


class MySQLHandlerClient(BaseSQLClient):
    """The handler's MySQL client — basic, IAM user, and IAM role.

    Sync SQLAlchemy engine on PyMySQL, driven off the event loop by the api
    package's ``BaseSQLClient``. Connects eagerly in ``load()``, as the
    worker's client does, so an auth failure surfaces there and the
    caching_sha2_password retry wraps a real connection attempt.

    Note: Database name is optional in MySQL connections. The connection
    template does not include a database, allowing connections without a
    default database, which matches the worker's client.
    """

    DB_CONFIG: Optional[DatabaseConfig] = DatabaseConfig(
        template="mysql+pymysql://{username}:{password}@{host}:{port}",
        required=list(REQUIRED_FIELDS),
        defaults=dict(CONNECTION_DEFAULTS),
        # SSL is set in load(); see create_ssl_context().
        connect_args={},
    )

    def __init__(self, *args: Any, probe_timeout: Optional[int] = None, **kwargs: Any):
        """Optionally bound this client's connect attempt.

        ``probe_timeout`` is seconds, and only the preflight path passes it.
        The instance always gets its own copy of ``DB_CONFIG``: ``load()``
        writes the TLS context into ``connect_args``, and the class-level dict
        is shared by every client in the process.
        """
        super().__init__(*args, **kwargs)
        base = type(self).DB_CONFIG
        if base is not None:
            self.DB_CONFIG = dataclasses.replace(
                base,
                defaults=with_connect_timeout(base.defaults, probe_timeout),
                connect_args=dict(base.connect_args or {}),
            )

    async def get_results(self, query: str) -> list[dict[str, Any]]:
        """All rows of ``query`` as a list of dicts."""
        rows: list[dict[str, Any]] = []
        async for batch in self.run_query(query):
            rows.extend(batch)
        return rows

    async def _test_connection(self) -> None:
        """Open one connection, so a refused login fails inside ``load()``."""
        async for _ in self.run_query("SELECT 1"):
            pass

    def get_iam_user_token(self) -> str:
        """An RDS IAM token signed with the customer's own access key."""
        fields = iam_user_fields(self.credentials)
        log_iam_user_fields(logger, fields)
        require_iam_user_fields(fields)
        try:
            session = create_aws_session({
                "aws_access_key_id": fields.aws_access_key_id,
                "aws_secret_access_key": fields.aws_secret_access_key,
            })
            rds = create_aws_client(
                service="rds", region=str(fields.region), session=session
            )
            token = rds.generate_db_auth_token(
                DBHostname=fields.host, Port=int(fields.port), DBUsername=fields.user
            )
        except Exception as e:
            raise IamTokenGenerationError(
                failure_reason="token_generation_failed", cause=e
            ) from e
        return require_token(token, logger)

    def get_iam_role_token(self) -> str:
        """An RDS IAM token signed with the assumed role's temporary credentials."""
        fields = iam_role_fields(self.credentials)
        log_iam_role_fields(logger, fields)
        require_iam_role_fields(fields)
        region = str(fields.region)
        explicit_keys = sts_explicit_keys(fields)
        assume_role_kwargs: dict[str, Any] = {
            "RoleArn": fields.aws_role_arn,
            "RoleSessionName": aws_session_name(),
        }
        # AWS STS rejects an empty ExternalId, so only send one that is set.
        if fields.external_id:
            assume_role_kwargs["ExternalId"] = fields.external_id
        try:
            if explicit_keys:
                sts = create_aws_client(
                    service="sts",
                    region=region,
                    session=create_aws_session(explicit_keys),
                )
            else:
                sts = create_aws_client(
                    service="sts", region=region, use_default_credentials=True
                )
            temp_credentials = sts.assume_role(**assume_role_kwargs)["Credentials"]
        except Exception as e:
            # "authentication failed" in the message, as on the worker, so the
            # SDK's auth classifier routes this to AuthError, not Internal.
            raise IamTokenGenerationError(
                message="AWS IAM role authentication failed — could not assume the configured role",
                failure_reason="assume_role_denied",
                cause=e,
            ) from e
        try:
            rds = create_aws_client(
                service="rds", region=region, temp_credentials=temp_credentials
            )
            token = rds.generate_db_auth_token(
                DBHostname=fields.host, Port=int(fields.port), DBUsername=fields.user
            )
        except Exception as e:
            raise IamTokenGenerationError(
                failure_reason="token_generation_failed", cause=e
            ) from e
        return require_token(token, logger)

    async def load(self, credentials: dict[str, Any]) -> None:
        """Build the engine for the credential's auth type and connect once."""
        self.credentials = credentials
        auth_type = str(credentials.get("authType", "basic")).lower()
        if auth_type in ("iam_user", "iam_role"):
            await self._load_iam(credentials, auth_type)
            return

        # For basic auth, enable SSL by default (matching legacy JDBC driver
        # behavior).
        if self.DB_CONFIG is not None:
            self.DB_CONFIG.connect_args = {
                **(self.DB_CONFIG.connect_args or {}),
                "ssl": create_ssl_context(),
            }
        flattened = flatten_basic_credentials(credentials)

        @cold_cache_retry(retry_if_exception(_is_connection_attempt))
        async def _load_with_retry() -> None:
            await self.close()
            await BaseSQLClient.load(self, flattened)
            try:
                await self._test_connection()
            except BaseException:
                await self.close()
                raise

        await _load_with_retry()

    async def _load_iam(self, credentials: dict[str, Any], auth_type: str) -> None:
        """Engine for IAM (user or role) authentication, connected once."""
        from sqlalchemy import create_engine, event  # noqa: PLC0415 — [sql] extra

        get_token = (
            self.get_iam_user_token
            if auth_type == "iam_user"
            else self.get_iam_role_token
        )
        # boto3 is synchronous and talks to STS/RDS over the network.
        raw_token = await asyncio.get_running_loop().run_in_executor(
            _iam_executor(), get_token
        )
        username = iam_db_username(credentials, auth_type)
        defaults = self.DB_CONFIG.defaults if self.DB_CONFIG else None
        url = iam_engine_url("mysql+pymysql", credentials, defaults)
        connect_args = iam_connect_args(
            self.DB_CONFIG.connect_args if self.DB_CONFIG else None, username, raw_token
        )
        self.engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        if not self.engine:
            raise EngineCreationError()
        event.listens_for(self.engine, "do_connect")(token_refresher(get_token, logger))

        try:
            await self._test_connection()
        except IamTokenGenerationError:
            await self.close()
            raise
        except Exception as e:
            await self.close()
            # The token was generated, so a connection-test failure here is
            # almost always MySQL rejecting it; "authentication failed" routes
            # it to AuthError, as on the worker.
            raise IamTokenGenerationError(
                message="AWS IAM authentication failed — MySQL rejected the connection after token injection",
                failure_reason="connection_rejected",
                cause=e,
            ) from e
