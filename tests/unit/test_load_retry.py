"""Regression tests for transient-connection retry on ``SQLClient.load()``.

The SDK base ``AsyncBaseSQLClient.load()`` wraps every credential-ping
failure as ``SqlClientAuthFailedError`` (non-retryable in Temporal). That's
the correct call for actual auth failures (bad creds, expired tokens) but
catastrophic for transient TCP drops on long-lived MySQL cron runs —
``[Errno 104] Connection reset by peer`` and MySQL 2013/2006 idle-wait
drops were surfacing as ``SqlClientAuthFailedError`` and failing
workflows that should simply reconnect.

The fix in ``app/clients/__init__.py`` wraps ``load()`` with bounded
retries that walk the exception chain for known transient markers.
Genuine auth failures still propagate immediately on the first attempt.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.clients import SQLClient, _is_transient_load_error


class TestIsTransientLoadError:
    def test_direct_errno_104(self) -> None:
        assert _is_transient_load_error(ConnectionResetError("[Errno 104] Connection reset by peer"))

    def test_mysql_2013_via_chain(self) -> None:
        inner = OSError("[Errno 104] Connection reset by peer")
        try:
            try:
                raise inner
            except OSError as e:
                raise RuntimeError(
                    "(pymysql.err.OperationalError) (2013, 'Lost connection to MySQL server during query')"
                ) from e
        except RuntimeError as wrap:
            assert _is_transient_load_error(wrap)

    def test_mysql_2006_gone_away(self) -> None:
        assert _is_transient_load_error(
            RuntimeError("(2006, 'MySQL server has gone away')")
        )

    def test_broken_pipe(self) -> None:
        assert _is_transient_load_error(BrokenPipeError("Broken pipe"))

    def test_auth_failure_not_transient(self) -> None:
        assert not _is_transient_load_error(
            RuntimeError("(1045, \"Access denied for user 'foo'@'%' (using password: YES)\")")
        )

    def test_dns_failure_not_transient(self) -> None:
        assert not _is_transient_load_error(
            RuntimeError("Name or service not known")
        )


class TestLoadRetry:
    @pytest.mark.asyncio
    async def test_retries_on_transient_then_succeeds(self) -> None:
        client = SQLClient()
        client.engine = None
        attempts: list[int] = []

        async def _fake_load_once(self, creds):  # noqa: ARG001
            attempts.append(len(attempts) + 1)
            if len(attempts) < 2:
                raise ConnectionResetError("[Errno 104] Connection reset by peer")
            return None

        with patch.object(SQLClient, "_load_once", _fake_load_once), patch(
            "app.clients.asyncio.sleep", AsyncMock()
        ):
            await client.load({"authType": "basic"})

        assert len(attempts) == 2  # retried once

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self) -> None:
        client = SQLClient()
        client.engine = None
        call_count = {"n": 0}

        async def _fake_load_once(self, creds):  # noqa: ARG001
            call_count["n"] += 1
            raise ConnectionResetError("[Errno 104] Connection reset by peer")

        with patch.object(SQLClient, "_load_once", _fake_load_once), patch(
            "app.clients.asyncio.sleep", AsyncMock()
        ):
            with pytest.raises(ConnectionResetError):
                await client.load({"authType": "basic"})

        assert call_count["n"] == 3  # full attempt budget

    @pytest.mark.asyncio
    async def test_auth_failure_does_not_retry(self) -> None:
        client = SQLClient()
        client.engine = None
        call_count = {"n": 0}

        async def _fake_load_once(self, creds):  # noqa: ARG001
            call_count["n"] += 1
            raise RuntimeError("(1045, \"Access denied for user\")")

        with patch.object(SQLClient, "_load_once", _fake_load_once), patch(
            "app.clients.asyncio.sleep", AsyncMock()
        ):
            with pytest.raises(RuntimeError, match="Access denied"):
                await client.load({"authType": "basic"})

        assert call_count["n"] == 1  # no retry on real auth error
