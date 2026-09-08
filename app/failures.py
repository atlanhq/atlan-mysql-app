from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from application_sdk.errors import (
    AppError,
    AppPermissionDeniedError,
    AuthError,
    InternalError,
    InvalidInputError,
    PreconditionError,
    RateLimitedError,
    SourceUnavailableError,
)


@dataclass(kw_only=True)
class CredentialFieldMissingError(InvalidInputError):
    code: ClassVar[str] = "INVALID_INPUT_MYSQL_CREDENTIAL_MISSING"


@dataclass(kw_only=True)
class RegionExtractionError(InvalidInputError):
    code: ClassVar[str] = "INVALID_INPUT_MYSQL_REGION"


@dataclass(kw_only=True)
class IamTokenGenerationError(AuthError):
    code: ClassVar[str] = "AUTH_MYSQL_IAM_TOKEN"
    message: str = "Failed to generate AWS RDS IAM authentication token"
    auth_method: str | None = "aws_iam"


@dataclass(kw_only=True)
class EngineCreationError(InternalError):
    code: ClassVar[str] = "INTERNAL_MYSQL_ENGINE_CREATE"
    message: str = "Failed to create async SQLAlchemy engine"
    component: str | None = "sql_client"


@dataclass(kw_only=True)
class MetadataHostMissingError(PreconditionError):
    code: ClassVar[str] = "PRECONDITION_MYSQL_METADATA_HOST"
    resource: str | None = "credentials"
    expected_state: str | None = "host present"
    actual_state: str | None = "host absent"


@dataclass(kw_only=True)
class MetadataFetchError(InternalError):
    code: ClassVar[str] = "INTERNAL_MYSQL_METADATA_FETCH"
    message: str = "Failed to fetch metadata from source database"
    component: str | None = "mysql_handler"


@dataclass(kw_only=True)
class PreflightAuthError(AuthError):
    code: ClassVar[str] = "AUTH_MYSQL_PREFLIGHT"
    message: str = "Could not authenticate to the MySQL source."
    suggested_action: str | None = (
        "Verify the host, port, and credentials, and that the database is "
        "reachable from Atlan."
    )


@dataclass(kw_only=True)
class TableListingError(AppPermissionDeniedError):
    code: ClassVar[str] = "PERMISSION_MYSQL_TABLE_LISTING"
    message: str = "Could not list the tables this connection can read."
    suggested_action: str | None = (
        "Grant SELECT on the databases you want to crawl to the connection's "
        "MySQL user, then run the workflow again."
    )
    required_action: str | None = "SELECT"


@dataclass(kw_only=True)
class ConnectionLimitError(RateLimitedError):
    code: ClassVar[str] = "RATE_LIMITED_MYSQL_CONNECTIONS"
    message: str = "The MySQL server is at its connection limit."
    suggested_action: str | None = (
        "Wait for open connections to close, or raise max_connections on the "
        "server, then run the workflow again."
    )
    limit_type: str | None = "connections"


@dataclass(kw_only=True)
class SourceRestartingError(SourceUnavailableError):
    code: ClassVar[str] = "SOURCE_UNAVAILABLE_MYSQL_CONNECTION_LOST"
    message: str = "The MySQL server closed the connection before the check finished."
    suggested_action: str | None = (
        "Wait for the server to accept connections again, then run the workflow again."
    )
    source_type: str | None = "mysql"


_CONNECTION_LIMIT_ERRNOS = frozenset({1040, 1203, 1226})
_SERVER_BLIP_ERRNOS = frozenset({1053, 2006, 2013})


def _mysql_errno(exc: BaseException) -> int | None:
    """Find the MySQL server error number in an exception chain.

    Driver errors reach the handler wrapped: SQLAlchemy keeps the DBAPI error in
    ``orig``, this app's own leaves keep it in ``__cause__``, and only the driver
    error itself carries the errno, as ``args[0]``.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        args = getattr(current, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
        current = getattr(current, "orig", None) or current.__cause__
    return None


def transient_failure(exc: BaseException) -> AppError | None:
    """Typed retryable leaf for a MySQL blip, or ``None`` when the failure is definitive.

    A blip must not block a hard preflight gate, so the caller reports it as a
    failed check on a ``PARTIAL`` verdict instead of ``NOT_READY``. Anything
    unrecognised stays definitive and keeps the caller's own leaf.
    """
    errno = _mysql_errno(exc)
    if errno in _CONNECTION_LIMIT_ERRNOS:
        return ConnectionLimitError(cause=exc)
    if errno in _SERVER_BLIP_ERRNOS:
        return SourceRestartingError(cause=exc)
    return None
