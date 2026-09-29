"""The MySQL app's handler as the consolidated API host installs it.

The code lives in ``app/`` (``app/handler.py``, ``app/client.py``, ...) and is
edited there; this wheel ships those files under this package (see
``api-files.txt``). The host discovers ``handler`` through the
``atlan.app_api`` entry point.
"""

from __future__ import annotations

from .handler import MySQLAppHandler

#: The instance the host serves (entry point ``atlan.app_api: mysql``).
handler = MySQLAppHandler()

__all__ = ["MySQLAppHandler", "handler"]
