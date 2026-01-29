import os
from typing import Any, Optional, Tuple

import daft
from application_sdk.constants import APPLICATION_NAME
from application_sdk.transformers.common.utils import (
    get_yaml_query_template_path_mappings,
)
from application_sdk.transformers.query import QueryBasedTransformer


class MySQLQueryBasedTransformer(QueryBasedTransformer):
    """MySQL-specific query-based transformer with custom YAML templates."""

    def __init__(self, connector_name: str, tenant_id: str, **kwargs: Any):
        super().__init__(connector_name, tenant_id, **kwargs)

        self.entity_class_definitions = get_yaml_query_template_path_mappings(
            custom_templates_path=os.path.join(
                os.path.dirname(__file__), "sql_query_templates"
            ),
            assets=["TABLE", "COLUMN", "DATABASE", "SCHEMA", "EXTRAS-PROCEDURE"],
        )

    def prepare_template_and_attributes(
        self,
        dataframe: daft.DataFrame,
        workflow_id: str,
        workflow_run_id: str,
        connection_qualified_name: Optional[str] = None,
        connection_name: Optional[str] = None,
        entity_sql_template_path: Optional[str] = None,
    ) -> Tuple[daft.DataFrame, str]:
        """
        Prepare the entity SQL template and the default attributes for the DataFrame.

        Overrides the base class to fix connection_qualified_name and connector_name:
        - Replaces 'default/default' with 'default/mysql' in connection_qualified_name
        - Uses APPLICATION_NAME ('mysql') for connector_name instead of extracting from connection_qualified_name

        Args:
            dataframe (daft.DataFrame): Input DataFrame
            workflow_id (str): ID of the workflow
            workflow_run_id (str): ID of the workflow run
            connection_qualified_name (str): Qualified name of the connection
            connection_name (str): Name of the connection
            entity_sql_template_path (str): Path to the entity SQL template

        Returns:
            Tuple[daft.DataFrame, str]: DataFrame with default attributes added and the entity SQL template
        """
        # Fix connection_qualified_name: replace 'default/default' with 'default/mysql'
        if connection_qualified_name and "default/default" in connection_qualified_name:
            connection_qualified_name = connection_qualified_name.replace(
                "default/default", f"default/{APPLICATION_NAME}"
            )

        # Call parent method with fixed connection_qualified_name
        dataframe, entity_sql_template = super().prepare_template_and_attributes(
            dataframe,
            workflow_id,
            workflow_run_id,
            connection_qualified_name,
            connection_name,
            entity_sql_template_path,
        )

        # Override connector_name to use APPLICATION_NAME instead of extracting from connection_qualified_name
        dataframe = dataframe.with_columns(
            {"connector_name": daft.lit(APPLICATION_NAME)}
        )

        return dataframe, entity_sql_template
