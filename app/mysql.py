"""MySQLApp — v3 SQL connector for MySQL databases.

Extends SqlApp with MySQL-specific SQL queries and asset mappers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from application_sdk.templates.sql_app import SqlApp

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER, TENANT_ID

# Read SQL files at module level
_SQL_DIR = Path(__file__).parent / "sql"


def _read_sql(filename: str) -> str:
    """Read a SQL file and replace database placeholder."""
    path = _SQL_DIR / filename
    if not path.exists():
        return ""
    sql = path.read_text().strip()
    return sql.replace("{database_placeholder}", DATABASE_PLACEHOLDER)


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
                "connectorName": "mysql",
                "connectionQualifiedName": connection_qn,
                "schemaCount": record.get("schema_count", 0),
            },
        }

    def map_schema(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw schema record to Atlan Schema entity."""
        db_name = record.get(
            "database_name", record.get("datname", DATABASE_PLACEHOLDER)
        )
        schema_name = record.get("schema_name", "")
        return {
            "typeName": "Schema",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": {
                "name": schema_name,
                "qualifiedName": f"{connection_qn}/{db_name}/{schema_name}",
                "connectorName": "mysql",
                "connectionQualifiedName": connection_qn,
                "databaseName": db_name,
                "databaseQualifiedName": f"{connection_qn}/{db_name}",
                "tableCount": record.get("table_count", 0),
            },
        }

    def map_table(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw table record to Atlan Table or View entity.

        MySQL extract_table.sql returns both tables and views in the same
        result set, differentiated by TABLE_TYPE column.
        """
        db_name = record.get(
            "database_name", record.get("datname", DATABASE_PLACEHOLDER)
        )
        schema_name = record.get("schema_name", "")
        table_name = record.get("table_name", "")
        table_type = record.get("TABLE_TYPE", record.get("table_type", "BASE TABLE"))

        # Determine entity type based on TABLE_TYPE
        if table_type.upper() in ("VIEW", "SYSTEM VIEW"):
            type_name = "View"
        else:
            type_name = "Table"

        return {
            "typeName": type_name,
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": {
                "name": table_name,
                "qualifiedName": f"{connection_qn}/{db_name}/{schema_name}/{table_name}",
                "connectorName": "mysql",
                "connectionQualifiedName": connection_qn,
                "databaseName": db_name,
                "databaseQualifiedName": f"{connection_qn}/{db_name}",
                "schemaName": schema_name,
                "schemaQualifiedName": f"{connection_qn}/{db_name}/{schema_name}",
                "tableType": table_type,
                "columnCount": record.get("column_count", 0),
                "rowCount": record.get("row_count", 0),
                "sizeBytes": record.get("size_bytes", 0),
            },
        }

    def map_column(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw column record to Atlan Column entity."""
        db_name = record.get(
            "database_name", record.get("datname", DATABASE_PLACEHOLDER)
        )
        schema_name = record.get("schema_name", "")
        table_name = record.get("table_name", "")
        column_name = record.get("column_name", "")

        return {
            "typeName": "Column",
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": {
                "name": column_name,
                "qualifiedName": f"{connection_qn}/{db_name}/{schema_name}/{table_name}/{column_name}",
                "connectorName": "mysql",
                "connectionQualifiedName": connection_qn,
                "databaseName": db_name,
                "schemaName": schema_name,
                "tableName": table_name,
                "tableQualifiedName": f"{connection_qn}/{db_name}/{schema_name}/{table_name}",
                "order": record.get("ordinal_position", record.get("column_order", 0)),
                "dataType": record.get("data_type", ""),
                "maxLength": record.get("character_maximum_length", 0),
                "isNullable": record.get("is_nullable", "YES") == "YES",
                "defaultValue": record.get("column_default"),
                "isPrimaryKey": record.get("is_primary_key", False),
            },
        }
