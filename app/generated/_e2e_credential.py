from pydantic import Field

from application_sdk.testing.e2e.credential import CredentialBody  # type: ignore[attr-defined]


class MySQLCredentialBody(CredentialBody):
    """AE credential body for the MySQL connector (basic auth).

    Serialises via ``model_dump(by_alias=True)`` into the ``payload[].body``
    block of the AE submit payload.  Fields follow the connector's
    ``atlan-connectors-mysql.json`` property schema: host/port/auth-type at
    the top level, username/password nested under the auth-type key.
    """

    host: str = Field(alias="host")
    port: int = Field(default=3306, alias="port")
    auth_type: str = Field(default="basic", alias="auth-type")
    username: str = Field(default="", alias="username")
    password: str = Field(default="", alias="password")
