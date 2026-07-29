from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from application_sdk.errors import (
    AuthError,
    InternalError,
    InvalidInputError,
    PreconditionError,
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
class InvalidCredentialError(AuthError):
    code: ClassVar[str] = "AUTH_MYSQL_INVALID_CREDENTIALS"
    message: str = "Invalid credentials: access denied for the configured MySQL user"


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
