import json
from pathlib import Path
from typing import Any, Dict

from application_sdk.clients.sql import BaseSQLClient
from application_sdk.handlers.sql import BaseSQLHandler
from application_sdk.observability.logger_adaptor import get_logger

logger = get_logger(__name__)


class MySQLHandler(BaseSQLHandler):
    """
    Handler for MySQL metadata extraction.
    """

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
