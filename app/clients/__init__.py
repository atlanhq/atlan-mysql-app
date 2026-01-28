from typing import Optional

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient


class SQLClient(AsyncBaseSQLClient):
    """
    This client handles connection string generation based on authentication
    type and manages database connectivity using SQLAlchemy.

    Note: Database name is optional in MySQL connections. The connection
    template does not include a database, allowing connections without a
    default database, which is compatible with MySQL's behavior and matches
    legacy connector behavior.
    """

    DB_CONFIG: Optional[DatabaseConfig] = DatabaseConfig(
        template="mysql+aiomysql://{username}:{password}@{host}:{port}",
        required=["username", "password", "host", "port"],
        defaults={
            "connect_timeout": 5,
            "charset": "utf8mb4",
        },
    )
