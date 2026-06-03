from pydantic import Field

from application_sdk.testing.e2e.credential import CredentialBody  # type: ignore[attr-defined]


class MySQLCredentialBody(CredentialBody):
    """AE credential body for the MySQL connector.

    In AGENT mode the body is lightweight — no host/username/password (those
    live in the agent's Dapr secret store, resolved via agent-json ref-keys at
    runtime).  Sending the DIRECT-mode shape in AGENT mode causes the
    orchestrator to skip credential creation, leaving {{credentialGuid}}
    unsubstituted and triggering HTTP 500 at submit time.
    """

    name: str = Field(alias="name")
    auth_type: str = Field(default="basic", alias="authType")
    connector_config_name: str = Field(
        default="atlan-connectors-mysql", alias="connectorConfigName"
    )
    extra: dict = Field(default_factory=dict, alias="extra")
