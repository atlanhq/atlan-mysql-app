"""MySQLApp — v3 SQL connector for MySQL databases.

Extends SqlApp with MySQL-specific SQL queries and asset mappers.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
from application_sdk.contracts.base import Output
from application_sdk.execution._temporal.activity_utils import get_object_store_prefix
from application_sdk.templates.contracts.sql_metadata import (
    ExtractionInput,
    FetchProceduresInput,
    TransformInput,
)
from application_sdk.templates.sql_app import SqlApp

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER, TENANT_ID
from app.handlers.mysql import (  # noqa: F401 — SDK discovers {AppClass}Handler by convention
    MySQLAppHandler,
)

# S3 bucket for QI + lineage-app — forwarded as extract output so the manifest
# JSONPath expressions ($.extract.outputs.storage_bucket) resolve correctly.
_S3_BUCKET = os.environ.get("S3_BUCKET", "")


class MySQLExtractionOutput(Output):
    """Extended extraction output for MySQL — includes lineage pipeline prefixes.

    The standard ExtractionOutput fields (connection_qualified_name,
    transformed_data_prefix, publish_state_prefix, current_state_prefix) are
    consumed by the publish node. The additional fields are consumed by the
    qi → lineage-app → lineage-publish nodes in the manifest DAG, mirroring
    the pattern used by the Athena native app.
    """

    # Standard publish inputs (match ExtractionOutput fields)
    connection_qualified_name: str = ""
    transformed_data_prefix: str = ""
    publish_state_prefix: str = ""
    current_state_prefix: str = ""

    # QI inputs/outputs
    view_lineage_output_prefix: str = ""

    # Lineage-app inputs/outputs
    lineage_stage_prefix: str = ""
    lineage_publish_state_prefix: str = ""
    lineage_current_state_prefix: str = ""

    # Forwarded to QI + lineage-app via manifest JSONPath
    storage_bucket: str = ""


# Read SQL files at module level
_SQL_DIR = Path(__file__).parent / "sql"


def _read_sql(filename: str) -> str:
    """Read a SQL file and replace database placeholder."""
    path = _SQL_DIR / filename
    if not path.exists():
        return ""
    sql = path.read_text().strip()
    return sql.replace("{database_placeholder}", DATABASE_PLACEHOLDER)


def _epoch_ms(value: Any) -> int | None:
    """Convert a datetime/timestamp to epoch milliseconds, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):  # type: ignore[arg-type]
            return None
        return int(ts.timestamp() * 1000)  # type: ignore[union-attr]
    except Exception:
        return None


def _sync_attrs(connection_name: str, workflow_id: str, run_id: str) -> dict:
    """Build lastSync* attributes from workflow context."""
    return {
        "connectionName": connection_name,
        "lastSyncWorkflowName": workflow_id,
        "lastSyncRun": run_id,
        "lastSyncRunAt": int(time.time() * 1000),
    }


def _coerce_numeric(v: Any, default: int = 0) -> int | float:
    """Return v as-is, but convert None / NaN / Inf to default.

    pandas represents SQL NULLs as NaN in numeric columns. Python's ``x or 0``
    guard doesn't catch NaN because ``bool(float('nan'))`` is True.
    """
    if v is None:
        return default
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return default
    return v


def _safe_str(v: Any) -> str:
    """Stringify v safely for customAttributes.

    - None  → ""
    - NaN / Inf → ""
    - whole-number float (1589248.0) → "1589248"  (matches legacy Argo output)
    - everything else → str(v)
    """
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        if v.is_integer():
            return str(int(v))
    return str(v) if not isinstance(v, str) else v


class MySQLApp(SqlApp):
    """MySQL metadata extraction App.

    Extends SqlApp with:
    - MySQL-specific SQL queries from app/sql/ files
    - Asset mapper functions for databases, schemas, tables, columns, views
    - SQLClient with basic + IAM user + IAM role authentication
    """

    name: ClassVar[str] = "mysql"

    sql_client_class: ClassVar = SQLClient  # type: ignore[assignment]

    # SQL templates from app/sql/ files
    fetch_database_sql: ClassVar[str] = _read_sql("extract_database.sql")
    fetch_schema_sql: ClassVar[str] = _read_sql("extract_schema.sql")
    fetch_table_sql: ClassVar[str] = _read_sql("extract_table.sql")
    fetch_column_sql: ClassVar[str] = _read_sql("extract_column.sql")
    fetch_procedure_sql: ClassVar[str] = _read_sql("extract_procedure.sql")

    # Temp table regex fragments
    extract_temp_table_regex_table_sql: ClassVar[str] = _read_sql(
        "extract_temp_table_regex_table.sql"
    )
    extract_temp_table_regex_column_sql: ClassVar[str] = _read_sql(
        "extract_temp_table_regex_column.sql"
    )

    # ── Asset mappers ───────────────────────────────────────────────────

    def map_database(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw database record to Atlan Database entity."""
        db_name = record.get("database_name", record.get("datname", ""))
        return {
            "typeName": "Database",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": {
                "name": db_name,
                "qualifiedName": f"{connection_qn}/{db_name}",
                "connectionQualifiedName": connection_qn,
                "connectorName": "mysql",
                "schemaCount": record.get("schema_count", 0),
                "tenantId": TENANT_ID,
            },
            "customAttributes": {},
        }

    def map_schema(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw schema record to Atlan Schema entity."""
        db_name = record.get(
            "catalog_name",
            record.get("database_name", record.get("datname", DATABASE_PLACEHOLDER)),
        )
        schema_name = record.get("schema_name", "")
        db_qn = f"{connection_qn}/{db_name}"
        return {
            "typeName": "Schema",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": {
                "name": schema_name,
                "qualifiedName": f"{db_qn}/{schema_name}",
                "connectionQualifiedName": connection_qn,
                "connectorName": "mysql",
                "databaseName": db_name,
                "databaseQualifiedName": db_qn,
                "tableCount": record.get("table_count", 0),
                "viewsCount": record.get("views_count", 0),
                "tenantId": TENANT_ID,
                "database": {
                    "typeName": "Database",
                    "uniqueAttributes": {"qualifiedName": db_qn},
                },
            },
            "customAttributes": {},
        }

    def map_table(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw table/view record to Atlan Table or View entity.

        MySQL extract_table.sql returns both tables and views in the same
        result set, differentiated by table_type / table_kind column.
        """
        db_name = record.get(
            "table_catalog",
            record.get("database_name", record.get("datname", DATABASE_PLACEHOLDER)),
        )
        schema_name = record.get("table_schema", record.get("schema_name", ""))
        table_name = record.get("table_name", "")
        table_kind = record.get(
            "table_kind", record.get("table_type", "BASE TABLE")
        ).upper()

        db_qn = f"{connection_qn}/{db_name}"
        schema_qn = f"{db_qn}/{schema_name}"
        entity_qn = f"{schema_qn}/{table_name}"

        is_view = table_kind in ("VIEW", "SYSTEM VIEW")
        type_name = "View" if is_view else "Table"

        attrs: dict[str, Any] = {
            "name": table_name,
            "qualifiedName": entity_qn,
            "connectionQualifiedName": connection_qn,
            "connectorName": "mysql",
            "databaseName": db_name,
            "databaseQualifiedName": db_qn,
            "schemaName": schema_name,
            "schemaQualifiedName": schema_qn,
            "columnCount": record.get("column_count", 0),
            "sizeBytes": record.get("size_bytes", 0),
            "isPartitioned": bool(record.get("is_partition", False)),
            "partitionCount": record.get("partition_count", 0),
            "tenantId": TENANT_ID,
            "atlanSchema": {
                "typeName": "Schema",
                "uniqueAttributes": {"qualifiedName": schema_qn},
            },
        }

        # Table-specific fields
        if not is_view:
            attrs["rowCount"] = record.get("row_count", 0)
            attrs["subType"] = "TABLE"

        # View-specific fields
        if is_view:
            view_body = record.get("view_definition", "") or ""
            if view_body:
                # Prepend CREATE VIEW so QI/gudusoft can identify the target view
                # and generate view→table lineage edges. MySQL's VIEW_DEFINITION
                # stores only the SELECT body without the CREATE VIEW prefix.
                attrs["definition"] = (
                    f"CREATE OR REPLACE VIEW {table_name} AS {view_body}"
                )
            else:
                attrs["definition"] = ""
            attrs["description"] = "VIEW"

        # Source timestamps
        source_created = _epoch_ms(record.get("create_time"))
        if source_created:
            attrs["sourceCreatedAt"] = source_created

        # Custom attributes (MySQL-specific metadata)
        custom: dict[str, Any] = {}
        for key in (
            "engine",
            "version",
            "row_format",
            "data_length",
            "table_collation",
            "create_options",
        ):
            custom[key] = _safe_str(record.get(key))
        custom["is_transient"] = ""

        return {
            "typeName": type_name,
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": attrs,
            "customAttributes": custom,
        }

    def map_column(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw column record to Atlan Column entity."""
        db_name = record.get(
            "table_catalog",
            record.get("database_name", record.get("datname", DATABASE_PLACEHOLDER)),
        )
        schema_name = record.get("table_schema", record.get("schema_name", ""))
        table_name = record.get("table_name", "")
        column_name = record.get("column_name", "")
        table_type = record.get("table_type", "BASE TABLE").upper()

        db_qn = f"{connection_qn}/{db_name}"
        schema_qn = f"{db_qn}/{schema_name}"
        table_qn = f"{schema_qn}/{table_name}"
        column_qn = f"{table_qn}/{column_name}"

        is_view = table_type in ("VIEW", "SYSTEM VIEW")
        constraint = record.get("constraint_type", "")

        attrs: dict[str, Any] = {
            "name": column_name,
            "qualifiedName": column_qn,
            "connectionQualifiedName": connection_qn,
            "connectorName": "mysql",
            "databaseName": db_name,
            "databaseQualifiedName": db_qn,
            "schemaName": schema_name,
            "schemaQualifiedName": schema_qn,
            "dataType": (record.get("data_type") or "").upper(),
            "isNullable": record.get("is_nullable", "YES") == "YES",
            "isPartition": False,
            "isPrimary": constraint == "PRIMARY KEY",
            "isForeign": constraint == "FOREIGN KEY",
            "maxLength": record.get(
                "max_length", record.get("character_maximum_length", 0)
            )
            or 0,
            "numericScale": _coerce_numeric(
                record.get("numeric_scale", record.get("decimal_digits"))
            ),
            "order": record.get("ordinal_position", 0),
            "precision": _coerce_numeric(record.get("numeric_precision")),
            "tenantId": TENANT_ID,
        }

        # Table or View relationship ref
        if is_view:
            attrs["viewName"] = table_name
            attrs["viewQualifiedName"] = table_qn
            attrs["view"] = {
                "typeName": "View",
                "uniqueAttributes": {"qualifiedName": table_qn},
            }
        else:
            attrs["tableName"] = table_name
            attrs["tableQualifiedName"] = table_qn
            attrs["table"] = {
                "typeName": "Table",
                "uniqueAttributes": {"qualifiedName": table_qn},
            }

        # Custom attributes (all raw SQL metadata)
        custom: dict[str, Any] = {}
        for key in (
            "ordinal_position",
            "is_self_referencing",
            "numeric_precision",
            "is_auto_increment",
            "is_generated",
            "extra_info",
            "character_set_name",
            "collation_name",
            "column_type",
            "column_key",
            "privileges",
            "generation_expression",
            "is_autoincrement",
            "is_generatedcolumn",
            "constraint_type",
            "constraint_name",
            "buffer_length",
            "column_size",
            "is_identity",
            "identity_cycle",
            "character_octet_length",
        ):
            val = record.get(key)
            if val is not None:
                custom[key] = val
            else:
                custom[key] = (
                    ""
                    if key
                    not in ("ordinal_position", "numeric_precision", "column_size")
                    else None
                )
        # Ensure type_name from data_type
        custom["type_name"] = (record.get("data_type") or "").lower()

        return {
            "typeName": "Column",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": attrs,
            "customAttributes": custom,
        }

    def map_procedure(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw procedure record to Atlan Procedure entity.

        The ``definition`` field contains the stored procedure SQL body. The
        publish-app's SQL parser reads this after ingestion to derive lineage
        (Process / ColumnProcess entities) — mirroring the legacy Argo connector's
        ``extras-procedure`` output which triggered the same SQL parser step.
        """
        catalog = record.get("procedure_catalog", DATABASE_PLACEHOLDER)
        schema = record.get("procedure_schema", "")
        name = record.get("procedure_name", "")
        definition = record.get("procedure_definition", "") or ""
        proc_type = record.get("procedure_type", "PROCEDURE")

        db_qn = f"{connection_qn}/{catalog}"
        schema_qn = f"{db_qn}/{schema}"
        # Qualified name matches legacy format: connection/db/schema/_procedures_/name
        proc_qn = f"{schema_qn}/_procedures_/{name}"

        attrs: dict[str, Any] = {
            "name": name,
            "qualifiedName": proc_qn,
            "connectionQualifiedName": connection_qn,
            "connectorName": "mysql",
            "databaseName": catalog,
            "databaseQualifiedName": db_qn,
            "schemaName": schema,
            "schemaQualifiedName": schema_qn,
            "definition": definition,
            "subType": proc_type,
            "tenantId": TENANT_ID,
            "atlanSchema": {
                "typeName": "Schema",
                "uniqueAttributes": {"qualifiedName": schema_qn},
            },
        }

        source_owner = record.get("source_owner", "") or ""
        if source_owner:
            attrs["sourceCreatedBy"] = source_owner

        source_created = _epoch_ms(record.get("created"))
        if source_created:
            attrs["sourceCreatedAt"] = source_created
        source_updated = _epoch_ms(record.get("last_altered"))
        if source_updated:
            attrs["sourceUpdatedAt"] = source_updated

        return {
            "typeName": "Procedure",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": attrs,
            "customAttributes": {},
        }

    async def run(  # type: ignore[override]
        self, input: ExtractionInput
    ) -> MySQLExtractionOutput:
        """MySQL extraction: standard assets + procedures + lineage pipeline outputs.

        1. Standard fetch/transform/upload (databases, schemas, tables, columns)
        2. Stored procedures — writes ``extras-procedure/`` so the QI SQL parser
           derives procedure-level lineage from ``definition`` fields
        3. Returns extended output with view_lineage_output_prefix,
           lineage_stage_prefix, and storage_bucket so the manifest DAG can
           chain qi → lineage-app → lineage-publish nodes (Athena pattern)
        """
        base_result = await super().run(input)

        if self.fetch_procedure_sql:
            cred_ref = self._resolve_credential_ref(input)
            proc_input = self.build_task_input(
                FetchProceduresInput, input, cred_ref=cred_ref
            )
            await self.fetch_procedures(proc_input)
            transform_input = self.build_task_input(
                TransformInput, input, cred_ref=cred_ref
            )
            await self.transform_procedures(transform_input)

        # SqlApp.run() exposes its resolved local base path via output_path so
        # subclasses can derive additional prefixes without re-calling workflow.info().
        base = base_result.output_path
        connection_qn = base_result.connection_qualified_name

        return MySQLExtractionOutput(
            connection_qualified_name=connection_qn,
            transformed_data_prefix=base_result.transformed_data_prefix,
            publish_state_prefix=base_result.publish_state_prefix,
            current_state_prefix=base_result.current_state_prefix,
            view_lineage_output_prefix=get_object_store_prefix(
                os.path.join(base, "view_lineage")
            ),
            lineage_stage_prefix=get_object_store_prefix(
                os.path.join(base, "lineage_stage")
            ),
            lineage_publish_state_prefix=get_object_store_prefix(
                os.path.join(base, "lineage_publish_state")
            ),
            lineage_current_state_prefix=get_object_store_prefix(
                os.path.join(base, "lineage_current_state")
            ),
            storage_bucket=_S3_BUCKET,
        )
