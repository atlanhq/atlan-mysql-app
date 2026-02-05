import json
from pathlib import Path
from typing import Any, Dict, Optional

from application_sdk.clients.sql import BaseSQLClient
from application_sdk.handlers.sql import BaseSQLHandler
from application_sdk.observability.logger_adaptor import get_logger

from app.constants import DATABASE_PLACEHOLDER

logger = get_logger(__name__)


def _replace_database_placeholder(sql: Optional[str]) -> Optional[str]:
    """Replace {database_placeholder} with the actual constant value.

    Args:
        sql: SQL query string that may contain {database_placeholder}

    Returns:
        SQL query with placeholder replaced, or None if input is None
    """
    if sql is None:
        return None
    return sql.replace("{database_placeholder}", DATABASE_PLACEHOLDER)


class MySQLHandler(BaseSQLHandler):
    """
    Handler for MySQL metadata extraction.
    """

    # Override SQL queries to replace {database_placeholder} with constant
    metadata_sql = _replace_database_placeholder(BaseSQLHandler.metadata_sql)
    tables_check_sql = _replace_database_placeholder(BaseSQLHandler.tables_check_sql)

    def __init__(self, sql_client: BaseSQLClient | None = None):
        # MySQL typically uses single database mode
        super().__init__(sql_client, multidb=False)

    @staticmethod
    async def get_configmap(config_map_id: str) -> Dict[str, Any]:
        """Get configuration map JSON for playground frontend.

        Args:
            config_map_id: The configuration map identifier.
                - "atlan-connectors-mysql" returns credential configuration
                - Any other value returns workflow configuration

        Returns:
            Dict[str, Any]: Configuration map as dictionary.
        """
        workflow_json_path = Path().cwd() / "app" / "templates" / "workflow.json"
        credential_json_path = (
            Path().cwd() / "app" / "templates" / "atlan-connectors-mysql.json"
        )

        if config_map_id == "atlan-connectors-mysql":
            with open(credential_json_path) as f:
                return json.load(f)

        with open(workflow_json_path) as f:
            return json.load(f)
