# Generated from contract/app.pkl via contract-toolkit. DO NOT EDIT.
# Regenerate with: pkl eval -m . contract/app.pkl
from pydantic import Field, BaseModel, ConfigDict

from application_sdk.testing.e2e.credential import CredentialBody


class MysqlCredentialBodyExtra(BaseModel):
    model_config = ConfigDict(
        frozen=True, populate_by_name=True, serialize_by_alias=True
    )

    username: str = Field(default="", alias="username")
    aws_role_arn: str = Field(default="", alias="aws_role_arn")
    aws_external_id: str = Field(default="", alias="aws_external_id")


class MysqlCredentialBody(CredentialBody):
    name: str = Field(alias="name")
    auth_type: str = Field(default="basic", alias="authType")
    host: str = Field(alias="host")
    port: int = Field(default=3306, alias="port")
    username: str = Field(default="", alias="username")
    password: str = Field(default="", alias="password")
    extra: MysqlCredentialBodyExtra = Field(
        default_factory=MysqlCredentialBodyExtra, alias="extra"
    )


class MysqlAgentCredentialBody(CredentialBody):
    name: str = Field(alias="name")
    auth_type: str = Field(default="basic", alias="authType")
    connector_config_name: str = Field(
        default="atlan-connectors-mysql", alias="connectorConfigName"
    )
    extra: dict = Field(default_factory=dict, alias="extra")
