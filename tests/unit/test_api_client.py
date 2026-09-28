"""The handler's MySQL client (atlan_mysql_api.client) on its IAM paths.

The basic path is driven end to end by test_preflight_conformance.py; these
cover what only IAM reaches: which AWS identity signs the token, and how each
failure is typed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from atlan_mysql_api.client import MySQLHandlerClient
from atlan_mysql_api.failures import (
    IamTokenGenerationError,
    RegionExtractionError,
)

RDS_HOST = "example-db.abc123xyz.us-east-1.rds.amazonaws.com"


def _client(credentials: dict[str, Any]) -> MySQLHandlerClient:
    client = MySQLHandlerClient()
    client.credentials = credentials
    return client


def _iam_user() -> dict[str, Any]:
    return {
        "authType": "iam_user",
        "host": RDS_HOST,
        "port": "3306",
        "username": "SYNTHETICACCESSKEY00",
        "password": "synthetic-secret",
        "extra": {"username": "db_user"},
    }


def _iam_role(**extra: Any) -> dict[str, Any]:
    return {
        "authType": "iam_role",
        "host": RDS_HOST,
        "port": "3306",
        "username": "db_user",
        "extra": {"aws_role_arn": "arn:aws:iam::000000000000:role/example", **extra},
    }


def test_iam_user_token_is_signed_with_the_customers_own_keys() -> None:
    rds = MagicMock()
    rds.generate_db_auth_token.return_value = "tok"
    with (
        patch("atlan_mysql_api.client.create_aws_session") as session,
        patch("atlan_mysql_api.client.create_aws_client", return_value=rds) as make,
    ):
        assert _client(_iam_user()).get_iam_user_token() == "tok"

    session.assert_called_once_with({
        "aws_access_key_id": "SYNTHETICACCESSKEY00",
        "aws_secret_access_key": "synthetic-secret",
    })
    assert make.call_args.kwargs["service"] == "rds"
    assert make.call_args.kwargs["region"] == "us-east-1"
    rds.generate_db_auth_token.assert_called_once_with(
        DBHostname=RDS_HOST, Port=3306, DBUsername="db_user"
    )


def test_iam_role_with_explicit_keys_never_falls_back_to_the_ambient_identity() -> None:
    """On the shared host the ambient identity is the host pod's, not the
    customer's — a supplied key pair must be what calls STS."""
    sts, rds = MagicMock(), MagicMock()
    sts.assume_role.return_value = {"Credentials": {"AccessKeyId": "x"}}
    rds.generate_db_auth_token.return_value = "tok"
    with (
        patch("atlan_mysql_api.client.create_aws_session") as session,
        patch(
            "atlan_mysql_api.client.create_aws_client", side_effect=[sts, rds]
        ) as make,
    ):
        token = _client(
            _iam_role(
                aws_access_key_id="SYNTHETICACCESSKEY00",
                aws_secret_access_key="synthetic-secret",
                aws_external_id="ext-id",
            )
        ).get_iam_role_token()

    assert token == "tok"
    session.assert_called_once_with({
        "aws_access_key_id": "SYNTHETICACCESSKEY00",
        "aws_secret_access_key": "synthetic-secret",
    })
    sts_call = make.call_args_list[0].kwargs
    assert sts_call["service"] == "sts"
    assert "use_default_credentials" not in sts_call
    assert sts.assume_role.call_args.kwargs["ExternalId"] == "ext-id"
    assert make.call_args_list[1].kwargs["temp_credentials"] == {"AccessKeyId": "x"}


def test_iam_role_without_keys_uses_the_default_chain() -> None:
    sts, rds = MagicMock(), MagicMock()
    sts.assume_role.return_value = {"Credentials": {}}
    rds.generate_db_auth_token.return_value = "tok"
    with patch(
        "atlan_mysql_api.client.create_aws_client", side_effect=[sts, rds]
    ) as make:
        _client(_iam_role()).get_iam_role_token()

    assert make.call_args_list[0].kwargs["use_default_credentials"] is True
    assert "ExternalId" not in sts.assume_role.call_args.kwargs


def test_assume_role_refusal_is_a_typed_auth_failure() -> None:
    sts = MagicMock()
    sts.assume_role.side_effect = RuntimeError("AccessDenied")
    with patch("atlan_mysql_api.client.create_aws_client", return_value=sts):
        with pytest.raises(IamTokenGenerationError) as raised:
            _client(_iam_role()).get_iam_role_token()
    assert raised.value.failure_reason == "assume_role_denied"
    assert "authentication failed" in raised.value.message


def test_empty_token_is_refused() -> None:
    rds = MagicMock()
    rds.generate_db_auth_token.return_value = ""
    with (
        patch("atlan_mysql_api.client.create_aws_session"),
        patch("atlan_mysql_api.client.create_aws_client", return_value=rds),
    ):
        with pytest.raises(IamTokenGenerationError) as raised:
            _client(_iam_user()).get_iam_user_token()
    assert raised.value.failure_reason == "empty_token"


def test_non_rds_host_is_a_typed_input_error() -> None:
    with pytest.raises(RegionExtractionError):
        _client({**_iam_user(), "host": "mysql.internal.example"}).get_iam_user_token()


async def test_rejected_iam_connection_is_typed_and_disposes_the_engine() -> None:
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("Access denied for user")
    client = MySQLHandlerClient()
    with (
        patch.object(MySQLHandlerClient, "get_iam_user_token", return_value="tok"),
        patch("sqlalchemy.create_engine", return_value=engine) as create,
        patch("sqlalchemy.event.listens_for") as listens_for,
    ):
        with pytest.raises(IamTokenGenerationError) as raised:
            await client.load(_iam_user())

    assert raised.value.failure_reason == "connection_rejected"
    connect_args = create.call_args.kwargs["connect_args"]
    assert connect_args["user"] == "db_user"
    assert connect_args["password"] == "tok"
    assert connect_args["auth_plugin"] == "mysql_clear_password"
    # The token rides connect_args, never the URL.
    assert "tok" not in create.call_args.args[0]
    listens_for.assert_called_once_with(engine, "do_connect")
    engine.dispose.assert_called_once()
    assert client.engine is None
