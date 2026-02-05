import os
from typing import Any, Dict, Optional, cast

import daft
from application_sdk.activities.common.models import ActivityStatistics
from application_sdk.activities.common.utils import auto_heartbeater
from application_sdk.activities.metadata_extraction.sql import (
    BaseSQLMetadataExtractionActivities,
    BaseSQLMetadataExtractionActivitiesState,
)
from application_sdk.common.types import DataframeType
from application_sdk.io.json import JsonFileWriter
from application_sdk.io.parquet import ParquetFileReader
from application_sdk.io.utils import is_empty_dataframe
from temporalio import activity

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER
from app.transformers.query import MySQLQueryBasedTransformer


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


class MySQLSQLMetadataExtractionActivities(BaseSQLMetadataExtractionActivities):
    """
    MySQL-specific metadata extraction activities.
    """

    sql_client_class = SQLClient
    transformer_class = MySQLQueryBasedTransformer

    # Override SQL queries to replace {database_placeholder} with constant
    fetch_database_sql = _replace_database_placeholder(
        BaseSQLMetadataExtractionActivities.fetch_database_sql
    )
    fetch_schema_sql = _replace_database_placeholder(
        BaseSQLMetadataExtractionActivities.fetch_schema_sql
    )
    fetch_table_sql = _replace_database_placeholder(
        BaseSQLMetadataExtractionActivities.fetch_table_sql
    )
    fetch_column_sql = _replace_database_placeholder(
        BaseSQLMetadataExtractionActivities.fetch_column_sql
    )
    fetch_procedure_sql = _replace_database_placeholder(
        BaseSQLMetadataExtractionActivities.fetch_procedure_sql
    )

    @activity.defn
    @auto_heartbeater
    async def transform_data(
        self,
        workflow_args: Dict[str, Any],
    ) -> ActivityStatistics:
        """Transforms raw data into the required format.

        Overrides base implementation to separate views from tables,
        writing views to transformed/view/ and tables to transformed/table/,
        matching the legacy connector's output structure.

        Args:
            workflow_args: Dictionary containing arguments for the workflow.

        Returns:
            ActivityStatistics: Combined statistics about the transformed data.
        """
        state = cast(
            BaseSQLMetadataExtractionActivitiesState,
            await self._get_state(workflow_args),
        )
        output_prefix, output_path, typename, workflow_id, workflow_run_id = (
            self._validate_output_args(workflow_args)
        )

        # Only handle table transformation (which includes views)
        if typename != "table":
            return await super().transform_data(workflow_args)

        raw_input = ParquetFileReader(
            path=os.path.join(output_path, "raw"),
            file_names=workflow_args.get("file_names"),
            dataframe_type=DataframeType.daft,
        )
        raw_input = raw_input.read_batches()

        # Create separate outputs for tables and views
        table_output = JsonFileWriter(
            path=os.path.join(output_path, "transformed"),
            typename="table",
            chunk_start=workflow_args.get("chunk_start"),
            dataframe_type=DataframeType.daft,
        )
        view_output = JsonFileWriter(
            path=os.path.join(output_path, "transformed"),
            typename="view",
            chunk_start=workflow_args.get("chunk_start"),
            dataframe_type=DataframeType.daft,
        )

        if state.transformer:
            workflow_args["connection_name"] = workflow_args.get("connection", {}).get(
                "connection_name", None
            )
            workflow_args["connection_qualified_name"] = workflow_args.get(
                "connection", {}
            ).get("connection_qualified_name", None)

            async for dataframe in raw_input:
                if not is_empty_dataframe(dataframe):
                    # Type cast: Since DataframeType.daft is specified, dataframe is a daft.DataFrame
                    daft_dataframe = cast(daft.DataFrame, dataframe)
                    transform_metadata = state.transformer.transform_metadata(
                        dataframe=daft_dataframe,
                        **workflow_args,  # type: ignore[arg-type]
                    )
                    if transform_metadata is not None:
                        # Filter views and tables based on typeName field

                        # Filter for views (typeName == "View")
                        view_filter = daft.col("typeName") == "View"
                        view_dataframe = transform_metadata.filter(view_filter)  # type: ignore[arg-type]

                        # Filter for tables (typeName == "Table" or "TablePartition")
                        table_filter = (daft.col("typeName") == "Table") | (
                            daft.col("typeName") == "TablePartition"
                        )
                        table_dataframe = transform_metadata.filter(table_filter)  # type: ignore[arg-type]

                        # Write views and tables separately
                        if not is_empty_dataframe(view_dataframe):
                            await view_output.write(view_dataframe)
                        if not is_empty_dataframe(table_dataframe):
                            await table_output.write(table_dataframe)

        # Close both outputs and combine statistics
        table_stats = await table_output.close()
        view_stats = await view_output.close()

        # Combine statistics
        combined_stats = ActivityStatistics(
            total_record_count=(
                (table_stats.total_record_count if table_stats else 0)
                + (view_stats.total_record_count if view_stats else 0)
            ),
            chunk_count=(
                (table_stats.chunk_count if table_stats else 0)
                + (view_stats.chunk_count if view_stats else 0)
            ),
            typename=typename,
            partitions=(
                (
                    table_stats.partitions
                    if table_stats and table_stats.partitions
                    else []
                )
                + (
                    view_stats.partitions
                    if view_stats and view_stats.partitions
                    else []
                )
            ),
        )

        return combined_stats
