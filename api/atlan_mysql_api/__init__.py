"""The MySQL app's handler, served by both the worker and the consolidated host.

Depends on ``atlan-application-sdk-api`` only — never on ``application_sdk`` —
so the host can mount it without the worker's dependency tree. The worker
(``app/``) imports the handler class from here; the host discovers ``handler``
through the ``atlan.app_api`` entry point.
"""

from __future__ import annotations

from pathlib import Path

from atlan_mysql_api.handler import MySQLAppHandler

#: The SQL the handler and the worker's extraction read.
SQL_DIR = Path(__file__).parent / "sql"

#: The instance the host serves (entry point ``atlan.app_api: mysql``).
handler = MySQLAppHandler()

__all__ = ["MySQLAppHandler", "SQL_DIR", "handler"]
