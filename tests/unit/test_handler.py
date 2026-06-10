"""Unit tests for MySQLHandler (v3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from application_sdk.handler import (
    AuthInput,
    AuthStatus,
    HandlerCredential,
    MetadataInput,
    PreflightInput,
    PreflightStatus,
)
from application_sdk.handler.contracts import BaseConnectionConfig

from app.handler import (
    MySQLAppHandler,
    _control_config_from_request,
    _creds_to_dict,
    _resolve_handler_sql,
)


class TestCredsToDict:
    """Test HandlerCredential → dict conversion."""

    def test_flat_credentials(self):
        creds = [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
        ]
        result = _creds_to_dict(creds)
        assert result["host"] == "localhost"
        assert result["port"] == "3306"
        assert result["username"] == "root"
        assert result["password"] == "secret"

    def test_extra_fields_nested(self):
        creds = [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="extra.database", value="mydb"),
            HandlerCredential(key="extra.charset", value="utf8mb4"),
        ]
        result = _creds_to_dict(creds)
        assert result["host"] == "localhost"
        assert result["extra"]["database"] == "mydb"
        assert result["extra"]["charset"] == "utf8mb4"

    def test_empty_credentials(self):
        result = _creds_to_dict([])
        assert result == {}


class TestMySQLHandlerAuth:
    """Test auth endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_auth_success(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(return_value=pd.DataFrame({"1": [1]}))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.SUCCESS
        assert "successful" in result.message.lower()

    @pytest.mark.asyncio
    async def test_auth_failure(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=valid_creds))

        assert result.status == AuthStatus.FAILED
        assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_auth_empty_credentials(self, handler):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=ValueError("Missing credentials"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.test_auth(AuthInput(credentials=[]))
        assert result.status == AuthStatus.FAILED


class TestMySQLHandlerPreflight:
    """Test preflight check endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_preflight_success(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(return_value=pd.DataFrame({"count": [42]}))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.READY
        assert len(result.checks) == 2
        assert all(c.passed for c in result.checks)

    @pytest.mark.asyncio
    async def test_preflight_auth_failure(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.load = AsyncMock(side_effect=Exception("Auth failed"))
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.NOT_READY


class TestMySQLHandlerMetadata:
    """Test metadata fetch endpoint."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_fetch_metadata_returns_schemas(self, handler, valid_creds):
        mock_client = AsyncMock()
        mock_client.get_results = AsyncMock(
            return_value=pd.DataFrame({
                "database_name": ["def", "def"],
                "schema_name": ["mydb", "testdb"],
            })
        )
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.fetch_metadata(
                MetadataInput(credentials=valid_creds)
            )

        assert len(result.objects) == 2
        assert result.objects[0].TABLE_SCHEMA == "mydb"
        assert result.objects[1].TABLE_SCHEMA == "testdb"

    @pytest.mark.asyncio
    async def test_fetch_metadata_raises_when_no_host(self, handler):
        """Empty credentials must raise, not silently return empty results.

        This guards against credential-resolution races where fetch_metadata
        is called before credentials are populated — previously this returned
        an empty SqlMetadataOutput which caused blank filter dropdowns in the UI.
        """
        with pytest.raises(Exception, match="no host in credentials"):
            await handler.fetch_metadata(MetadataInput(credentials=[]))


class TestMySQLHandlerClonedInformationSchema:
    """internal-ref: handler endpoints honor a customer-provided mirror schema.

    The marketplace UI surfaces these via BaseConnectionConfig (extra='allow')
    on PreflightInput/MetadataInput. With no override configured, behavior
    must be byte-identical to today.
    """

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.fixture
    def valid_creds(self):
        return [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="root"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
        ]

    @pytest.mark.asyncio
    async def test_preflight_uses_mirror_schema_when_configured(
        self, handler, valid_creds
    ):
        """When clonedInformationSchema is set, the tables-check SQL must
        target the mirror schema (e.g. atlan_meta.TABLES) and never the
        native information_schema."""
        captured_sql = []

        async def _capture(sql, *args, **kwargs):
            captured_sql.append(sql)
            return pd.DataFrame({"count": [42]})

        mock_client = AsyncMock()
        mock_client.get_results.side_effect = _capture
        mock_client.close = AsyncMock()

        # PreflightInput accepts a connection_config — BaseConnectionConfig
        # has extra='allow' so custom-control-config fields pass through.
        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        })

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds, connection_config=conn_cfg)
            )

        assert result.status == PreflightStatus.READY
        # _TEST_AUTH_SQL (SELECT 1) is run first; the second call is the
        # tables-check, which must reference the mirror schema.
        assert any("atlan_meta.TABLES" in sql for sql in captured_sql)
        assert not any("information_schema.TABLES" in sql for sql in captured_sql)
        # And the mirror must appear in the exclusion list so its own
        # pass-through views (atlan_meta.SCHEMATA, atlan_meta.COLUMNS, ...)
        # aren't double-counted when the connector walks user schemas.
        assert any(
            "NOT IN ('mysql', 'performance_schema', 'information_schema', "
            "'sys', 'atlan_meta')" in sql
            for sql in captured_sql
        )

    @pytest.mark.asyncio
    async def test_preflight_uses_canonical_schema_by_default(
        self, handler, valid_creds
    ):
        """Without control-config, preflight queries information_schema directly
        — exactly the pre-internal-ref behavior."""
        captured_sql = []

        async def _capture(sql, *args, **kwargs):
            captured_sql.append(sql)
            return pd.DataFrame({"count": [42]})

        mock_client = AsyncMock()
        mock_client.get_results.side_effect = _capture
        mock_client.close = AsyncMock()

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.preflight_check(
                PreflightInput(credentials=valid_creds)
            )

        assert result.status == PreflightStatus.READY
        # Canonical path uses information_schema.TABLES
        assert any("information_schema.TABLES" in sql for sql in captured_sql)
        assert not any("atlan_meta." in sql for sql in captured_sql)
        # The rendered exclusion list must equal the pre-fix literal — drifting
        # this changes the user-asset surface and counts as a regression.
        assert any(
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')" in sql
            for sql in captured_sql
        )

    @pytest.mark.asyncio
    async def test_fetch_metadata_uses_mirror_schema_when_configured(
        self, handler, valid_creds
    ):
        """fetch_metadata routes through the mirror schema when configured."""
        captured_sql = []

        async def _capture(sql, *args, **kwargs):
            captured_sql.append(sql)
            return pd.DataFrame({"database_name": ["def"], "schema_name": ["mydb"]})

        mock_client = AsyncMock()
        mock_client.get_results.side_effect = _capture
        mock_client.close = AsyncMock()

        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        })

        with patch("app.handler.SQLClient", return_value=mock_client):
            result = await handler.fetch_metadata(
                MetadataInput(credentials=valid_creds, connection_config=conn_cfg)
            )

        assert len(result.objects) == 1
        assert any("atlan_meta.SCHEMATA" in sql for sql in captured_sql)
        assert not any("information_schema.SCHEMATA" in sql for sql in captured_sql)
        # Mirror must also be excluded from the rendered NOT IN list so that
        # filter_metadata.sql doesn't return atlan_meta as a discovered schema.
        assert any(
            "NOT IN ('mysql', 'performance_schema', 'information_schema', "
            "'sys', 'atlan_meta')" in sql
            for sql in captured_sql
        )


# ── internal-ref: clonedInformationSchema on the credentials page ─────────


class TestControlConfigFromRequest:
    """`_control_config_from_request` decides which mirror schema wins.

    Precedence: credential field > legacy Control Config JSON. Both paths
    feed into the same resolver, so the rest of the connector is
    config-source-agnostic.
    """

    def test_no_credentials_no_connection_config_returns_empty(self):
        assert _control_config_from_request(None, None) == {}
        assert _control_config_from_request([], None) == {}

    def test_credentials_only_with_mirror(self):
        creds = [
            HandlerCredential(key="host", value="db.example.com"),
            HandlerCredential(key="extra.clonedInformationSchema", value="atlan_meta"),
        ]
        assert _control_config_from_request(creds, None) == {
            "clonedInformationSchema": "atlan_meta"
        }

    def test_credentials_with_empty_mirror_value_ignored(self):
        """Empty/whitespace credential value must not override anything."""
        creds = [HandlerCredential(key="extra.clonedInformationSchema", value="")]
        assert _control_config_from_request(creds, None) == {}
        creds = [HandlerCredential(key="extra.clonedInformationSchema", value="   ")]
        assert _control_config_from_request(creds, None) == {}

    def test_legacy_connection_config_only(self):
        """Backward compat: Control Config JSON still works when no credential value."""
        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "legacy_meta"},
        })
        assert _control_config_from_request(None, conn_cfg) == {
            "clonedInformationSchema": "legacy_meta"
        }

    def test_credential_wins_over_legacy_when_both_set(self):
        """If a customer sets both (e.g. mid-migration), the credential value
        is authoritative — that's the supported configuration going forward."""
        creds = [
            HandlerCredential(key="extra.clonedInformationSchema", value="new_meta"),
        ]
        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "legacy_meta"},
        })
        assert _control_config_from_request(creds, conn_cfg) == {
            "clonedInformationSchema": "new_meta"
        }

    def test_whitespace_in_credential_value_stripped(self):
        creds = [
            HandlerCredential(
                key="extra.clonedInformationSchema", value="  atlan_meta  "
            )
        ]
        assert _control_config_from_request(creds, None) == {
            "clonedInformationSchema": "atlan_meta"
        }


class TestResolveHandlerSqlFromCredential:
    """End-to-end: credential-page value drives the resolver."""

    _TEMPLATE = (
        "SELECT * FROM {information_schema}.TABLES T "
        "WHERE T.TABLE_SCHEMA NOT IN ({excluded_schemas})"
    )

    def test_credential_value_routes_through_mirror(self):
        creds = [
            HandlerCredential(key="host", value="db.example.com"),
            HandlerCredential(key="extra.clonedInformationSchema", value="atlan_meta"),
        ]
        sql = _resolve_handler_sql(self._TEMPLATE, creds, None)
        assert "atlan_meta.TABLES" in sql
        assert "information_schema.TABLES" not in sql
        # Mirror also added to exclusion list — no leakage as user asset.
        assert (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', "
            "'sys', 'atlan_meta')" in sql
        )

    def test_no_credential_no_connection_config_uses_default(self):
        sql = _resolve_handler_sql(self._TEMPLATE, None, None)
        assert "information_schema.TABLES" in sql
        assert (
            "NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')" in sql
        )
        assert "atlan_meta" not in sql

    def test_invalid_credential_value_raises(self):
        """Bad identifier on the credential side must fail loudly — preflight
        catches it before any SQL leaves the worker."""
        creds = [
            HandlerCredential(
                key="extra.clonedInformationSchema", value="bad;DROP TABLE"
            ),
        ]
        with pytest.raises(ValueError, match="clonedInformationSchema"):
            _resolve_handler_sql(self._TEMPLATE, creds, None)


class TestPreflightWithCredentialField:
    """Integration: preflight honors clonedInformationSchema from credentials."""

    @pytest.fixture
    def handler(self):
        return MySQLAppHandler()

    @pytest.mark.asyncio
    async def test_preflight_uses_mirror_from_credential_field(self, handler):
        """When clonedInformationSchema is on the credential record (internal-ref's
        new canonical location), preflight's tables-check must target the
        mirror — without any Control Config JSON being set."""
        captured_sql = []

        async def _capture(sql, *args, **kwargs):
            captured_sql.append(sql)
            return pd.DataFrame({"count": [42]})

        mock_client = AsyncMock()
        mock_client.get_results.side_effect = _capture
        mock_client.close = AsyncMock()

        creds = [
            HandlerCredential(key="host", value="localhost"),
            HandlerCredential(key="port", value="3306"),
            HandlerCredential(key="username", value="atlan_reader"),
            HandlerCredential(key="password", value="secret"),
            HandlerCredential(key="authType", value="basic"),
            HandlerCredential(key="extra.clonedInformationSchema", value="atlan_meta"),
        ]

        with patch("app.handler.SQLClient", return_value=mock_client):
            # No connection_config — only the credential field carries the
            # mirror name. This is the new canonical path.
            result = await handler.preflight_check(PreflightInput(credentials=creds))

        assert result.status == PreflightStatus.READY
        # Tables-check rendered the mirror schema.
        assert any("atlan_meta.TABLES" in sql for sql in captured_sql)
        assert not any("information_schema.TABLES" in sql for sql in captured_sql)
        # And appended the mirror to the exclusion list.
        assert any(
            "NOT IN ('mysql', 'performance_schema', 'information_schema', "
            "'sys', 'atlan_meta')" in sql
            for sql in captured_sql
        )
