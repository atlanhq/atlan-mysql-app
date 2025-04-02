from typing import Any, Dict, Generator

import pandas as pd
from application_sdk.activities.common.utils import auto_heartbeater
from application_sdk.activities.metadata_extraction.sql import (
    SQLMetadataExtractionActivities,
)
from application_sdk.decorators import transform
from application_sdk.inputs.sql_query import SQLQueryInput
from application_sdk.outputs.json import JsonOutput
from temporalio import activity

from app.clients import MySQLClient
from app.const import (
    COLUMN_EXTRACTION_SQL,
    COLUMN_EXTRACTION_TEMP_TABLE_REGEX_SQL,
    DATABASE_EXTRACTION_SQL,
    PROCEDURE_EXTRACTION_SQL,
    SCHEMA_EXTRACTION_SQL,
    TABLE_EXTRACTION_SQL,
    TABLE_EXTRACTION_TEMP_TABLE_REGEX_SQL,
)
from app.handlers import MySQLWorkflowHandler
from app.transformers.atlas import MySQLAtlasTransformer


class MySQLMetadataExtractionActivities(SQLMetadataExtractionActivities):
    """
    Activities for extracting metadata from MySQL databases.

    This class extends SQLMetadataExtractionActivities to provide MySQL-specific
    extraction functionality.
    """

    # Configure SQL queries
    fetch_database_sql = DATABASE_EXTRACTION_SQL
    fetch_schema_sql = SCHEMA_EXTRACTION_SQL
    fetch_table_sql = TABLE_EXTRACTION_SQL
    fetch_column_sql = COLUMN_EXTRACTION_SQL
    fetch_procedure_sql = PROCEDURE_EXTRACTION_SQL

    # Configure temp table regex SQL
    tables_extraction_temp_table_regex_sql = TABLE_EXTRACTION_TEMP_TABLE_REGEX_SQL
    column_extraction_temp_table_regex_sql = COLUMN_EXTRACTION_TEMP_TABLE_REGEX_SQL

    # Configure client and handler classes
    sql_client_class = MySQLClient
    handler_class = MySQLWorkflowHandler
    transformer_class = MySQLAtlasTransformer

    @activity.defn
    @auto_heartbeater
    @transform(
        batch_input=SQLQueryInput(query="fetch_procedure_sql"),
        raw_output=JsonOutput(output_suffix="/raw/extras-procedure"),
    )
    async def fetch_procedures(
        self,
        batch_input: Generator[pd.DataFrame, None, None],
        raw_output: JsonOutput,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Fetch and transform MySQL stored procedures and functions."""
        await raw_output.write_batched_dataframe(batch_input)
        return await raw_output.get_statistics(typename="extras-procedure")
