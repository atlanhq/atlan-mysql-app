"""MySQL API server package — built on atlan-server-sdk."""

from mysql_server.server import get_asgi_app

__all__ = ["get_asgi_app"]
