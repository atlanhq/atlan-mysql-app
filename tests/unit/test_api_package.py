"""The handler lives once, in atlan_mysql_api, and both surfaces serve it.

* The worker (``app/mysql.py``) uses the very class the api package defines —
  the SDK's preflight gate and SDR workflows call that handler.
* The consolidated host builds its ASGI app from ``atlan_mysql_api.handler``
  with ``application_sdk.handler.asgi.build_asgi_app`` and nothing from the worker.
* Importing the api package loads no worker-only code: the host installs only
  ``atlan-application-sdk-api``. (CI's api-member job proves it for real, in a
  venv holding only the api distribution.)
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import atlan_mysql_api
from application_sdk.handler.asgi import build_asgi_app
from atlan_mysql_api.handler import MySQLAppHandler
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def _closed_port() -> int:
    """A local port nothing listens on, so the connect is refused at once."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_worker_serves_the_api_packages_handler_class() -> None:
    from app import mysql as worker  # noqa: PLC0415 — the worker module under test

    assert worker.MySQLAppHandler is MySQLAppHandler
    # The package attribute is the served instance (entry point
    # ``atlan_mysql_api:handler``); it shadows the ``handler`` submodule as an
    # attribute, so the class is imported with ``from ... import``.
    assert isinstance(atlan_mysql_api.handler, MySQLAppHandler)


def test_host_serves_the_handler_and_a_dead_source_is_a_verdict() -> None:
    app = build_asgi_app(
        atlan_mysql_api.handler,
        app_name="mysql",
        app_package="atlan_mysql_api",
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/workflows/v1/auth",
        json={
            "credentials": {
                "host": "127.0.0.1",
                "port": str(_closed_port()),
                "username": "synthetic_user",
                "password": "SyntheticPw0000",
                "authType": "basic",
            }
        },
    )

    assert resp.status_code != 500, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["success"] is False
    assert body["data"]["status"] == "failed"
    assert body["data"]["error"]["code"] == "AUTH_MYSQL_PREFLIGHT"
    assert "SyntheticPw0000" not in resp.text


#: Worker-only code the api distribution does not ship.
_WORKER_ONLY = (
    "application_sdk.app",
    "application_sdk.execution",
    "application_sdk.infrastructure",
    "application_sdk.storage",
    "application_sdk.templates",
    "temporalio",
    "dapr",
    "obstore",
)


def test_importing_the_api_package_loads_no_worker_only_code() -> None:
    probe = (
        "import json, sys\n"
        "import atlan_mysql_api\n"
        f"worker = {_WORKER_ONLY!r}\n"
        "leaked = sorted(m for m in sys.modules\n"
        "    if any(m == w or m.startswith(w + '.') for w in worker))\n"
        "print(json.dumps(leaked))\n"
    )
    # Same interpreter as the suite, where the full SDK IS installed — so an
    # empty list means nothing imported it, not that it was unavailable.
    import application_sdk.execution  # noqa: F401, PLC0415 — proves the probe can see it

    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []
