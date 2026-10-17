"""Typed failures for the serving path.

Mirrors ``app/failures.py`` leaf for leaf, on ``server_sdk``.

Every class here inherits the categorical leaf that already carries its
``category`` and specialises via ``code`` only. That is possible because
``server_sdk.errors.leaves`` now ships one leaf per FailureCategory; it
previously shipped four, so the categories this connector reports — permission,
precondition, rate-limited, source-unavailable — had nothing to inherit from and
were declared against ``AppError`` with a P002 suppression on every line.

The ``code`` strings are the worker's, unchanged. They are what the UI keys on,
so a failure must read identically whether this app is consolidated or on its
own pod.
"""

from __future__ import annotations

from typing import ClassVar

from server_sdk.errors.base import AppError
from server_sdk.errors.leaves import (
    AppPermissionDeniedError,
    AuthError,
    InternalError,
    InvalidInputError,
    PreconditionError,
    RateLimitedError,
    SourceUnavailableError,
)
from server_sdk.errors.wire import Audience


class CredentialFieldMissingError(InvalidInputError):
    """A credential field the chosen auth type requires was not supplied."""

    code: ClassVar[str] = "INVALID_INPUT_MYSQL_CREDENTIAL_MISSING"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class RegionExtractionError(InvalidInputError):
    """The AWS region could not be derived from the RDS hostname."""

    code: ClassVar[str] = "INVALID_INPUT_MYSQL_REGION"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class IamTokenGenerationError(AuthError):
    """RDS IAM token generation failed (assume-role denied, or empty token)."""

    code: ClassVar[str] = "AUTH_MYSQL_IAM_TOKEN"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class EngineCreationError(InternalError):
    """The SQLAlchemy engine could not be constructed."""

    code: ClassVar[str] = "INTERNAL_MYSQL_ENGINE_CREATE"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.APP_OWNER


class MetadataHostMissingError(PreconditionError):
    """fetch_metadata was called before credential resolution supplied a host."""

    code: ClassVar[str] = "PRECONDITION_MYSQL_METADATA_HOST"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class MetadataFetchError(InternalError):
    """Metadata listing failed for a reason this app does not classify."""

    code: ClassVar[str] = "INTERNAL_MYSQL_METADATA_FETCH"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.APP_OWNER


class PreflightAuthError(AuthError):
    """Preflight could not authenticate, for a definitive reason."""

    code: ClassVar[str] = "AUTH_MYSQL_PREFLIGHT"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class TableListingError(AppPermissionDeniedError):
    """The role authenticated but cannot list tables."""

    code: ClassVar[str] = "PERMISSION_MYSQL_TABLE_LISTING"
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.USER


class ConnectionLimitError(RateLimitedError):
    """The server refused the connection because it is at its limit."""

    code: ClassVar[str] = "RATE_LIMITED_MYSQL_CONNECTIONS"
    retryable: ClassVar[bool] = True
    audience: ClassVar[Audience] = Audience.USER


class SourceRestartingError(SourceUnavailableError):
    """The connection dropped because the server is going away / restarting."""

    code: ClassVar[str] = "SOURCE_UNAVAILABLE_MYSQL_CONNECTION_LOST"
    retryable: ClassVar[bool] = True
    audience: ClassVar[Audience] = Audience.USER


#: Errnos the worker treats as a blip rather than a verdict. Kept as the
#: worker's sets, because which errno is transient is a source fact.
_CONNECTION_LIMIT_ERRNOS = frozenset({1040, 1203, 1226})
_SERVER_BLIP_ERRNOS = frozenset({1053, 2006, 2013})


def _mysql_errno(exc: BaseException) -> int | None:
    """Find the MySQL server error number in an exception chain.

    Driver errors arrive wrapped: SQLAlchemy keeps the DBAPI error in ``orig``,
    this package's own leaves keep it in ``__cause__``, and only the driver
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
    """Typed retryable leaf for a MySQL blip, or None when definitive.

    A blip must not block a hard preflight gate, so the caller reports it as a
    failed check on a PARTIAL verdict instead of NOT_READY. Anything
    unrecognised stays definitive and keeps the caller's own leaf.
    """
    errno = _mysql_errno(exc)
    if errno in _CONNECTION_LIMIT_ERRNOS:
        return ConnectionLimitError(cause=exc)
    if errno in _SERVER_BLIP_ERRNOS:
        return SourceRestartingError(cause=exc)
    return None
