from application_sdk.clients.sql import AsyncBaseSQLClient


class SQLClient(AsyncBaseSQLClient):
    """
    This client handles connection string generation based on authentication
    type and manages database connectivity using SQLAlchemy.
    """

    DB_CONFIG = {
        "template": "mysql+aiomysql://{username}:{password}@{host}:{port}/{database}",
        "required": ["username", "password", "host", "port", "database"],
        "defaults": {
            "connect_timeout": 5,
            "charset": "utf8mb4",
        },
    }
