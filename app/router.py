"""Per-app server router for the consolidated runtime.

Tracking: ARUN-546 (this PR) under ARUN-342 (parent — server consolidation).

Exports ``server_router`` so the ``common-app-server`` runtime can mount
this app via :func:`application_sdk.routing.host_apps`::

    # in common-app-server's main.py
    from mysql_app.router import server_router as mysql_router

    app = host_apps([
        ("mysql", mysql_router),
        ...
    ])

Construction:
    The router is a FastAPI sub-app produced by the SDK's
    ``create_app_handler_service`` factory wired to this app's
    :class:`MySQLHandler`. Workflow context (Temporal client, secret
    store, etc.) is read from environment at request time inside the
    handler — no per-request setup at import time.

Prerequisite:
    This module requires ``application-sdk`` >= 3.x with the
    ``application_sdk.routing`` module (added in ARUN-543). The dep
    in ``pyproject.toml`` must be bumped from the current v2.x pin
    to the consolidation-compatible v3 release before this import
    will succeed.
"""

from __future__ import annotations

try:
    from application_sdk.handler.service import create_app_handler_service

    from app.handlers.mysql import MySQLHandler
except ImportError as exc:
    raise ImportError(
        "atlan-mysql-app: server_router requires application-sdk >= 3.x "
        "with the routing module from ARUN-543. Bump the dep in "
        "pyproject.toml and re-sync."
    ) from exc


server_router = create_app_handler_service(
    handler=MySQLHandler(),
    app_name="mysql",
)
