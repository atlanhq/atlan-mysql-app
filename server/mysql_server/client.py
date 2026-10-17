"""MySQL client for the serving path — basic, IAM user, and IAM role.

Deliberately different from ``app/client.py`` in one respect, and it is the
reason this file is not a copy.

The worker generates an RDS IAM token by writing ``AWS_ACCESS_KEY_ID`` and
``AWS_SECRET_ACCESS_KEY`` into ``os.environ`` so boto3's default credential
chain picks them up, then restoring them in a ``finally``. In a process that
serves one app that is merely untidy. The consolidated host serves several apps
in ONE process with ONE environment, so it is a live fault:

* another app reading AWS credentials during that window — the object store,
  another connector's IAM path — gets this tenant's customer keys;
* two overlapping requests interleave, and the second ``finally`` restores a
  value the first request had already replaced;
* boto3 prefers env credentials over the pod's IRSA identity, so the host can
  try to reach its own bucket as the customer.

None of that is theoretical: ``test_auth`` and ``preflight_check`` both reach
this path, so any IAM-role MySQL connection triggers it on every call.

So the token is generated with credentials passed explicitly, through
server-sdk's AWS helpers. Nothing here reads or writes ``os.environ``.
"""

from __future__ import annotations

import ssl
from typing import Any, ClassVar

from server_sdk.aws import (
    assume_role_across_regions,
    create_aws_client,
    create_aws_session,
    create_engine_url,
    get_region_name_from_hostname,
)
from server_sdk.clients.sql import BaseSQLClient, DatabaseConfig
from server_sdk.observability.logger_adaptor import get_logger

from mysql_server.errors import (
    CredentialFieldMissingError,
    IamTokenGenerationError,
    RegionExtractionError,
)

logger = get_logger(__name__)

#: RDS IAM tokens are only valid over TLS, and the token is a bearer secret.
_IAM_SSL_CONTEXT_CACHE: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    """A default-verifying TLS context, built once.

    Built once because constructing a context loads the trust store, and doing
    that per request on a shared host process is real overhead for every
    co-tenant app, not just this one.
    """
    global _IAM_SSL_CONTEXT_CACHE
    if _IAM_SSL_CONTEXT_CACHE is None:
        _IAM_SSL_CONTEXT_CACHE = ssl.create_default_context()
    return _IAM_SSL_CONTEXT_CACHE


def _extra(credentials: dict[str, Any]) -> dict[str, Any]:
    """The ``extra`` sub-dict, tolerating the flattened ``extra.x`` wire form."""
    extra = credentials.get("extra")
    if isinstance(extra, dict):
        return extra
    flattened = {
        key[len("extra.") :]: value
        for key, value in credentials.items()
        if key.startswith("extra.")
    }
    return flattened


def _region_for(host: str | None) -> str:
    if not host:
        raise CredentialFieldMissingError(
            message="host is required to derive the AWS region for IAM authentication",
        )
    try:
        return get_region_name_from_hostname(host)
    except Exception as exc:  # noqa: BLE001 — normalised to this app's leaf
        raise RegionExtractionError(
            message=(
                "Region could not be extracted from the RDS hostname; expected "
                "[identifier].[region].rds.amazonaws.com"
            ),
            cause=exc,
        ) from exc


class MySQLServerClient(BaseSQLClient):
    """Serving-path MySQL client.

    No database in the template: MySQL connects without a default database, and
    the worker's connection string omits it too — adding one here would reject
    connections the worker accepts.
    """

    DB_CONFIG: ClassVar[DatabaseConfig | None] = DatabaseConfig(
        template="mysql+pymysql://{username}:{password}@{host}:{port}",
        required=["username", "password", "host", "port"],
        defaults={"connect_timeout": 5, "charset": "utf8mb4"},
        connect_args={},
    )

    def _rds_auth_token(
        self,
        *,
        client: Any,
        host: str,
        port: Any,
        user: str,
    ) -> str:
        token = client.generate_db_auth_token(
            DBHostname=host, Port=int(port or 3306), DBUsername=user
        )
        if not token:
            raise IamTokenGenerationError(
                message="AWS RDS IAM token generation returned an empty token",
            )
        return token

    def _iam_user_url(self, credentials: dict[str, Any]) -> str:
        """IAM user: the customer's own access key signs the RDS token.

        Legacy marketplace mapping, unchanged from the worker:
        ``credentials.username`` is the AWS access key id,
        ``credentials.password`` the secret, and ``extra.username`` the MySQL
        database user.
        """
        extra = _extra(credentials)
        host = credentials.get("host")
        db_user = extra.get("username")
        if not db_user:
            raise CredentialFieldMissingError(
                message=(
                    "extra.username (MySQL database user) is required for IAM "
                    "user authentication"
                ),
            )
        region = _region_for(host)
        # Explicit session from the supplied keys — never staged into os.environ.
        session = create_aws_session(credentials)
        rds = create_aws_client(service="rds", region=region, session=session)
        token = self._rds_auth_token(
            client=rds, host=str(host), port=credentials.get("port"), user=db_user
        )
        return create_engine_url(
            "mysql+pymysql",
            username=db_user,
            password=token,
            host=str(host),
            port=credentials.get("port"),
            # MySQL connects without a default database and the worker's
            # template omits it; "" renders a bare trailing slash, which is
            # equivalent. Naming one the customer did not pick would reject
            # connections the worker accepts.
            database=str(extra.get("database") or ""),
        )

    def _iam_role_url(self, credentials: dict[str, Any]) -> str:
        """IAM role: assume the role, then sign the token with its temp creds."""
        extra = _extra(credentials)
        host = credentials.get("host")
        db_user = credentials.get("username")  # MySQL DB user, not an AWS principal
        role_arn = extra.get("aws_role_arn")
        if not role_arn:
            raise CredentialFieldMissingError(
                message="extra.aws_role_arn is required for IAM role authentication",
            )
        if not db_user:
            raise CredentialFieldMissingError(
                message="username (MySQL database user) is required for IAM role authentication",
            )
        region = _region_for(host)
        try:
            temp_credentials = assume_role_across_regions(
                role_arn,
                external_id=extra.get("aws_external_id") or None,
                region_hint=region,
            )
        except Exception as exc:  # noqa: BLE001 — normalised to this app's leaf
            # Message keeps the worker's "authentication failed" wording so the
            # SDK's auth classifier routes this to AuthError, not Internal.
            raise IamTokenGenerationError(
                message=(
                    "AWS IAM role authentication failed — could not assume the "
                    "configured role"
                ),
                cause=exc,
            ) from exc
        rds = create_aws_client(
            service="rds", region=region, temp_credentials=temp_credentials
        )
        token = self._rds_auth_token(
            client=rds, host=str(host), port=credentials.get("port"), user=db_user
        )
        return create_engine_url(
            "mysql+pymysql",
            username=db_user,
            password=token,
            host=str(host),
            port=credentials.get("port"),
            # MySQL connects without a default database and the worker's
            # template omits it; "" renders a bare trailing slash, which is
            # equivalent. Naming one the customer did not pick would reject
            # connections the worker accepts.
            database=str(extra.get("database") or ""),
        )

    async def load(self, credentials: dict[str, Any]) -> None:
        """Build the engine for the credential's auth type."""
        auth_type = str(credentials.get("authType", "basic")).lower()
        if auth_type not in ("iam_user", "iam_role"):
            await super().load(credentials)
            return

        self.credentials = credentials
        # boto3 is synchronous and talks to STS/RDS over the network, so it runs
        # off the event loop — on a shared host process, blocking the loop
        # stalls every co-tenant app's requests, not just this one.
        import asyncio  # noqa: PLC0415 — local to keep import cost off mount

        url = await asyncio.to_thread(
            self._iam_user_url if auth_type == "iam_user" else self._iam_role_url,
            credentials,
        )
        base = type(self).DB_CONFIG
        if base is not None:
            connect_args = dict(base.connect_args or {})
            connect_args["ssl"] = _ssl_context()
            self.DB_CONFIG = DatabaseConfig(
                template=base.template,
                required=base.required,
                defaults=base.defaults,
                connect_args=connect_args,
            )
        self._build_engine(url)
