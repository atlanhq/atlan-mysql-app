from typing import Optional

from application_sdk.clients.models import DatabaseConfig
from application_sdk.clients.sql import AsyncBaseSQLClient


class SQLClient(AsyncBaseSQLClient):
    """
    This client handles connection string generation based on authentication
    type and manages database connectivity using SQLAlchemy.
    """

    DB_CONFIG: Optional[DatabaseConfig] = DatabaseConfig(
        template="mysql+aiomysql://{username}:{password}@{host}:{port}/{database}",
        required=["username", "password", "host", "port", "database"],
        defaults={
            "connect_timeout": 5,
            "charset": "utf8mb4",
        },
    )
