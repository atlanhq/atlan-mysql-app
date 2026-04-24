import json
from pathlib import Path
from typing import Any, Dict, Optional

from application_sdk.clients.sql import BaseSQLClient
from application_sdk.handlers.sql import BaseSQLHandler
from application_sdk.observability.logger_adaptor import get_logger

from app.activities.metadata_extraction.utils import resolve_cloned_information_schema
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

    # Insert {cloned_information_schema} placeholders for runtime resolution
    if metadata_sql:
        metadata_sql = metadata_sql.replace(
            "information_schema.", "{cloned_information_schema}"
        )
    if tables_check_sql:
        tables_check_sql = tables_check_sql.replace(
            "information_schema.", "{cloned_information_schema}"
        )

    def __init__(self, sql_client: BaseSQLClient | None = None):
        # MySQL typically uses single database mode
        super().__init__(sql_client, multidb=False)

    async def prepare_metadata(self, workflow_args=None, **kwargs):
        if workflow_args:
            self.metadata_sql = resolve_cloned_information_schema(
                workflow_args=workflow_args,
                default_sql=self.__class__.metadata_sql,
            )
        return await super().prepare_metadata(workflow_args=workflow_args, **kwargs)

    async def preflight_check(self, workflow_args=None, **kwargs):
        if workflow_args:
            self.tables_check_sql = resolve_cloned_information_schema(
                workflow_args=workflow_args,
                default_sql=self.__class__.tables_check_sql,
            )
        return await super().preflight_check(workflow_args=workflow_args, **kwargs)

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
