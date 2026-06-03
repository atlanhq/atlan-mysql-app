from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from application_sdk.errors import (
    Audience,
    AuthError,
    DependencyUnavailableError,
    InternalError,
    InvalidInputError,
    PreconditionError,
)


@dataclass(kw_only=True)
class CredentialFieldMissingError(InvalidInputError):
    code: ClassVar[str] = "INVALID_INPUT_MYSQL_CREDENTIAL_MISSING"


@dataclass(kw_only=True)
class MysqlSourceUnreachableError(DependencyUnavailableError):
    """The customer's MySQL source is unreachable from the worker.

    USER-audienced override of :class:`DependencyUnavailableError`: the
    unreachable target is the customer's RDS endpoint / VPC / security
    group / IP allowlist / DNS — Atlan oncall cannot fix it. Use for
    network / DNS / TLS / connection-refused failures at connect time,
    BEFORE any auth handshake completes (auth-class failures should
    surface as :class:`IamTokenGenerationError` or the SDK's
    :class:`AuthError`, not this).

    Raise this from the SQL client's connect path when the underlying
    driver exception (typically ``aiomysql.OperationalError``) has no
    auth keywords in the message — the SDK's ``prime_sql_auth`` then
    preserves the typing through to the wire envelope and on-call
    routing correctly attributes the failure to the customer rather
    than to Atlan.
    """

    code: ClassVar[str] = "DEPENDENCY_UNAVAILABLE_MYSQL_SOURCE"
    audience: ClassVar[Audience] = Audience.USER
    message: str = "MySQL source is unreachable from the worker"
    service: str | None = "mysql_source"


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
