"""Typed failures for the serving path.

Mirrors ``app/failures.py`` leaf for leaf, but on ``server_sdk``: the serving
package carries no application-sdk taxonomy, and server-sdk's own leaf set is
deliberately small (AuthError, InvalidInputError, InternalError,
DependencyUnavailableError), so the categories this connector actually reports
— permission, rate-limited, source-unavailable — are declared here against
``AppError`` directly.

The ``code`` strings are the worker's, unchanged. They are what the UI keys on,
so a failure must read identically whether this app is consolidated or on its
own pod.
"""

from __future__ import annotations

from typing import ClassVar

from server_sdk.errors.leaves import AppError
from server_sdk.errors.wire import Audience, FailureCategory


class _MySQLError(AppError):
    """Base for the serving-path MySQL leaves."""

    audience: ClassVar[Audience] = Audience.USER


class CredentialFieldMissingError(_MySQLError):
    """A credential field the chosen auth type requires was not supplied."""

    code: ClassVar[str] = "INVALID_INPUT_MYSQL_CREDENTIAL_MISSING"
    category: ClassVar[FailureCategory] = FailureCategory.INVALID_INPUT
    retryable: ClassVar[bool] = False


class RegionExtractionError(_MySQLError):
    """The AWS region could not be derived from the RDS hostname."""

    code: ClassVar[str] = "INVALID_INPUT_MYSQL_REGION"
    category: ClassVar[FailureCategory] = FailureCategory.INVALID_INPUT
    retryable: ClassVar[bool] = False


class IamTokenGenerationError(_MySQLError):
    """RDS IAM token generation failed (assume-role denied, or empty token)."""

    code: ClassVar[str] = "AUTH_MYSQL_IAM_TOKEN"
    category: ClassVar[FailureCategory] = FailureCategory.AUTH
    retryable: ClassVar[bool] = False


class EngineCreationError(_MySQLError):
    """The SQLAlchemy engine could not be constructed."""

    code: ClassVar[str] = "INTERNAL_MYSQL_ENGINE_CREATE"
    category: ClassVar[FailureCategory] = FailureCategory.INTERNAL
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.APP_OWNER


class MetadataHostMissingError(_MySQLError):
    """fetch_metadata was called before credential resolution supplied a host."""

    code: ClassVar[str] = "PRECONDITION_MYSQL_METADATA_HOST"
    category: ClassVar[FailureCategory] = FailureCategory.PRECONDITION
    retryable: ClassVar[bool] = False


class MetadataFetchError(_MySQLError):
    """Metadata listing failed for a reason this app does not classify."""

    code: ClassVar[str] = "INTERNAL_MYSQL_METADATA_FETCH"
    category: ClassVar[FailureCategory] = FailureCategory.INTERNAL
    retryable: ClassVar[bool] = False
    audience: ClassVar[Audience] = Audience.APP_OWNER


class PreflightAuthError(_MySQLError):
    """Preflight could not authenticate, for a definitive reason."""

    code: ClassVar[str] = "AUTH_MYSQL_PREFLIGHT"
    category: ClassVar[FailureCategory] = FailureCategory.AUTH
    retryable: ClassVar[bool] = False


class TableListingError(_MySQLError):
    """The role authenticated but cannot list tables."""

    code: ClassVar[str] = "PERMISSION_MYSQL_TABLE_LISTING"
    category: ClassVar[FailureCategory] = FailureCategory.PERMISSION
    retryable: ClassVar[bool] = False


class ConnectionLimitError(_MySQLError):
    """The server refused the connection because it is at its limit."""

    code: ClassVar[str] = "RATE_LIMITED_MYSQL_CONNECTIONS"
    category: ClassVar[FailureCategory] = FailureCategory.RATE_LIMITED
    retryable: ClassVar[bool] = True


class SourceRestartingError(_MySQLError):
    """The connection dropped because the server is going away / restarting."""

    code: ClassVar[str] = "SOURCE_UNAVAILABLE_MYSQL_CONNECTION_LOST"
    category: ClassVar[FailureCategory] = FailureCategory.SOURCE_UNAVAILABLE
    retryable: ClassVar[bool] = True


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
