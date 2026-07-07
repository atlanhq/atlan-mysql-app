"""Integration tests for agent-shape credential resolution.

Covers the two live production resolution paths that the workflow uses
to turn an ``agent_json`` spec into a flat credential dict:

1. **secret-path / JSON-string bundle** (``nestedSeparator=":" Dapr`` mode) —
   ``DaprCredentialVault`` or any ``SecretStore`` whose ``get()`` returns a
   JSON-encoded string.  ``_fetch_bundle`` must parse it via
   ``orjson.loads(raw)``.  This was previously exercised only by the SDR
   pipeline (``make-secrets.py`` + ``nestedSeparator=":" Dapr`` component),
   which has been removed.

2. **single-key** (``key-type: single-key``) — each ref-key in the spec is
   fetched as a separate top-level secret store entry.  Used by the full-DAG
   e2e and any production deployment that writes one env/secret per
   credential field.

The existing integration tests (``test_mysql_workflow.py``) cover the
``multiValued=true`` Dapr path — ``SecretStore.get()`` returns a dict
directly (``isinstance(raw, dict)`` branch in ``_fetch_bundle``).  These
tests fill the remaining gap without requiring a second Dapr sidecar.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from application_sdk.credentials.agent import resolve_agent_json
from application_sdk.credentials.errors import (
    CredentialNotFoundError,
    CredentialParseError,
)
from application_sdk.infrastructure.secrets import SecretNotFoundError

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal SecretStore stubs
# ---------------------------------------------------------------------------


class _JsonStringSecretStore:
    """Simulates Dapr secretstores.local.file with nestedSeparator=":".

    GetSecret(key) returns the raw JSON-encoded string stored under that
    key — the same as what Dapr returns in nestedSeparator mode.
    """

    def __init__(self, secrets: dict[str, dict[str, Any]]) -> None:
        self._raw = {k: json.dumps(v) for k, v in secrets.items()}

    async def get(self, name: str) -> str:
        if name not in self._raw:
            raise SecretNotFoundError(name)
        return self._raw[name]

    async def get_optional(self, name: str) -> str | None:
        return self._raw.get(name)

    async def get_bulk(self, names: list[str]) -> dict[str, str]:
        return {n: self._raw[n] for n in names if n in self._raw}

    async def list_names(self) -> list[str]:
        return list(self._raw)


class _FlatSecretStore:
    """Simulates Dapr secretstores.local.env (single-key mode).

    Each credential field is stored as its own top-level key.
    """

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    async def get(self, name: str) -> str:
        if name not in self._secrets:
            raise SecretNotFoundError(name)
        return self._secrets[name]

    async def get_optional(self, name: str) -> str | None:
        return self._secrets.get(name)

    async def get_bulk(self, names: list[str]) -> dict[str, str]:
        return {n: self._secrets[n] for n in names if n in self._secrets}

    async def list_names(self) -> list[str]:
        return list(self._secrets)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOST = "127.0.0.1"
_PORT = 3306

# Agent spec template matching the SDR pipeline's agent_json shape
# (same as BaseSDRIntegrationTest.agent_spec_template in the SDK docs).
_SECRET_PATH_SPEC = json.dumps({
    "agent-name": "mysql-ci-agent",
    "secret-manager": "local",
    "secret-path": "mysql-credentials",
    "auth-type": "basic",
    "host": _HOST,
    "port": _PORT,
    "basic.username": "username",
    "basic.password": "password",
})

# Agent spec for single-key mode — ref-keys are the env var / secret names.
_SINGLE_KEY_SPEC = json.dumps({
    "agent-name": "mysql-ci-agent",
    "secret-manager": "local",
    "key-type": "single-key",
    "auth-type": "basic",
    "host": _HOST,
    "port": _PORT,
    "basic.username": "SDR_MYSQL_USERNAME",
    "basic.password": "SDR_MYSQL_PASSWORD",
})


# ---------------------------------------------------------------------------
# secret-path / JSON-string bundle (nestedSeparator=":" path)
# ---------------------------------------------------------------------------


class TestSecretPathJsonStringBundle:
    """Exercises the orjson.loads(raw) branch in _fetch_bundle.

    This is the path exercised in production when Dapr's local.file
    secretstore is configured with nestedSeparator=":".
    """

    @pytest.fixture
    def store(self) -> _JsonStringSecretStore:
        return _JsonStringSecretStore({
            "mysql-credentials": {"username": "testuser", "password": "testpass"},
        })

    @pytest.mark.asyncio
    async def test_resolves_username_and_password(
        self, store: _JsonStringSecretStore
    ) -> None:
        result = await resolve_agent_json(_SECRET_PATH_SPEC, store)
        assert result["username"] == "testuser"
        assert result["password"] == "testpass"

    @pytest.mark.asyncio
    async def test_preserves_host_and_port(self, store: _JsonStringSecretStore) -> None:
        result = await resolve_agent_json(_SECRET_PATH_SPEC, store)
        assert result["host"] == _HOST
        assert result["port"] == _PORT

    @pytest.mark.asyncio
    async def test_sets_auth_type_and_credential_source(
        self, store: _JsonStringSecretStore
    ) -> None:
        result = await resolve_agent_json(_SECRET_PATH_SPEC, store)
        assert result["authType"] == "basic"
        assert result["credentialSource"] == "agent"

    @pytest.mark.asyncio
    async def test_missing_secret_path_raises(self) -> None:
        empty_store = _JsonStringSecretStore({})
        with pytest.raises(CredentialNotFoundError):
            await resolve_agent_json(_SECRET_PATH_SPEC, empty_store)

    @pytest.mark.asyncio
    async def test_invalid_json_in_bundle_raises(self) -> None:
        class _BrokenStore:
            async def get(self, name: str) -> str:
                return "not-valid-json{"

            async def get_optional(self, name: str) -> str | None:
                return None

            async def get_bulk(self, names: list[str]) -> dict[str, str]:
                return {}

            async def list_names(self) -> list[str]:
                return []

        with pytest.raises(CredentialParseError):
            await resolve_agent_json(_SECRET_PATH_SPEC, _BrokenStore())

    @pytest.mark.asyncio
    async def test_non_object_json_in_bundle_raises(self) -> None:
        class _ArrayStore:
            async def get(self, name: str) -> str:
                return json.dumps(["not", "a", "dict"])

            async def get_optional(self, name: str) -> str | None:
                return None

            async def get_bulk(self, names: list[str]) -> dict[str, str]:
                return {}

            async def list_names(self) -> list[str]:
                return []

        with pytest.raises(CredentialParseError):
            await resolve_agent_json(_SECRET_PATH_SPEC, _ArrayStore())


# ---------------------------------------------------------------------------
# single-key mode (key-type: single-key)
# ---------------------------------------------------------------------------


class TestSingleKeyResolution:
    """Exercises _fetch_per_key_bundle — each ref-key fetched individually.

    Used by the full-DAG e2e (make-secrets-e2e-full.py writes a flat
    {SDR_MYSQL_USERNAME: ..., SDR_MYSQL_PASSWORD: ...} bundle).
    """

    @pytest.fixture
    def store(self) -> _FlatSecretStore:
        return _FlatSecretStore({
            "SDR_MYSQL_USERNAME": "e2e_user",
            "SDR_MYSQL_PASSWORD": "e2e_pass",
        })

    @pytest.mark.asyncio
    async def test_resolves_username_and_password(
        self, store: _FlatSecretStore
    ) -> None:
        result = await resolve_agent_json(_SINGLE_KEY_SPEC, store)
        assert result["username"] == "e2e_user"
        assert result["password"] == "e2e_pass"

    @pytest.mark.asyncio
    async def test_preserves_host_and_port(self, store: _FlatSecretStore) -> None:
        result = await resolve_agent_json(_SINGLE_KEY_SPEC, store)
        assert result["host"] == _HOST
        assert result["port"] == _PORT

    @pytest.mark.asyncio
    async def test_sets_auth_type_and_credential_source(
        self, store: _FlatSecretStore
    ) -> None:
        result = await resolve_agent_json(_SINGLE_KEY_SPEC, store)
        assert result["authType"] == "basic"
        assert result["credentialSource"] == "agent"

    @pytest.mark.asyncio
    async def test_missing_keys_leave_ref_key_as_literal(self) -> None:
        # single-key mode silently skips missing store entries; the ref-key
        # value is left as-is (e.g. "SDR_MYSQL_USERNAME") and downstream
        # connect errors surface the problem.
        empty_store = _FlatSecretStore({})
        result = await resolve_agent_json(_SINGLE_KEY_SPEC, empty_store)
        assert result["username"] == "SDR_MYSQL_USERNAME"
        assert result["password"] == "SDR_MYSQL_PASSWORD"
