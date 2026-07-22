"""MySQLApp — v3 SQL connector for MySQL databases.

Extends SqlApp with MySQL-specific SQL queries and asset mappers.
"""

from __future__ import annotations

import math
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import orjson
import pandas as pd
from application_sdk.contracts.base import Output
from application_sdk.contracts.storage import UploadInput
from application_sdk.execution import get_object_store_prefix
from application_sdk.observability.logger_adaptor import get_logger
from application_sdk.templates.contracts.sql_metadata import (
    ExtractionInput,
    ExtractionTaskInput,
)
from application_sdk.templates.sql_app import SqlApp
from pyatlan_v9.model.assets import Column, Database, Procedure, Schema, Table, View

from app.client import SQLClient
from app.completeness import find_incomplete_levels, transformed_level_presence
from app.constants import DATABASE_PLACEHOLDER, TENANT_ID
from app.failures import IncompleteExtractionError
from app.handler import (  # noqa: F401 — SDK discovers {AppClass}Handler by convention
    MySQLAppHandler,
)

logger = get_logger(__name__)

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
    # pd.Timestamp raises ValueError (incl. DateParseError / OutOfBoundsDatetime),
    # TypeError, or OverflowError on malformed input — catch exactly those so a
    # genuine bug (e.g. an AttributeError) still surfaces instead of coercing to None.
    except (ValueError, TypeError, OverflowError):
        logger.debug("Could not coerce value to epoch ms", exc_info=True)
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


def _asset_to_dict(asset: Any) -> dict[str, Any]:
    """Serialize a pyatlan_v9 Asset via its canonical ``to_nested_bytes()`` wire shape.

    Returned as a dict (not the raw ``Asset``) because the installed SDK's
    ``SqlApp._transform_entity`` only recognises a mapper return value that
    exposes ``to_nested_dict``/``model_dump``/``dict`` — none of which exist on
    the msgspec-based ``Asset`` — and silently falls back to writing the
    unmapped raw record otherwise. Parsing the same bytes it would itself
    write keeps `.creator()` as the single owner of qualifiedName grammar and
    attribute placement while staying on the dict branch the base class
    already handles correctly.
    """
    return orjson.loads(asset.to_nested_bytes())


@lru_cache(maxsize=4096)
def _database_qn(name: str, connection_qn: str) -> str:
    """Database qualifiedName, derived via ``.creator()`` and memoized.

    Every schema/table/column record under the same database would otherwise
    re-derive this identical value — a MySQL sync can process thousands of
    column rows per database, so building a throwaway ``Database`` asset per
    row just to read its ``qualified_name`` is real, not just cosmetic, waste.
    """
    qn = Database.creator(
        name=name, connection_qualified_name=connection_qn
    ).qualified_name
    assert isinstance(qn, str)
    return qn


@lru_cache(maxsize=4096)
def _schema_qn(name: str, database_qn: str) -> str:
    """Schema qualifiedName, derived via ``.creator()`` and memoized (see ``_database_qn``)."""
    qn = Schema.creator(name=name, database_qualified_name=database_qn).qualified_name
    assert isinstance(qn, str)
    return qn


@lru_cache(maxsize=4096)
def _table_qn(name: str, schema_qn: str, is_view: bool) -> str:
    """Table/View qualifiedName, derived via ``.creator()`` and memoized (see ``_database_qn``)."""
    cls = View if is_view else Table
    qn = cls.creator(name=name, schema_qualified_name=schema_qn).qualified_name
    assert isinstance(qn, str)
    return qn


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
        """Map raw database record to Atlan Database entity.

        No ``description`` is set: the 'def' catalog isn't a real MySQL object
        at all — it's a fixed placeholder the JDBC/ODBC driver convention uses
        to satisfy the catalog+schema hierarchy MySQL doesn't actually have
        (MySQL only has one level: schema == database). There is nothing to
        attach a comment to. Contrast table/view/column/procedure, whose
        ``remarks`` field (their respective real *_COMMENT columns) is wired
        into ``description`` below.
        """
        db_name = record.get("database_name", record.get("datname", ""))
        asset = Database.creator(name=db_name, connection_qualified_name=connection_qn)
        asset.schema_count = record.get("schema_count", 0)
        asset.tenant_id = TENANT_ID
        asset.status = "ACTIVE"
        return _asset_to_dict(asset)

    def map_schema(self, record: dict[str, Any], connection_qn: str) -> dict:
        """Map raw schema record to Atlan Schema entity.

        No ``description`` is set: MySQL genuinely has no schema/database-level
        comment concept — ``information_schema.SCHEMATA`` has exactly six
        columns (CATALOG_NAME, SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME,
        DEFAULT_COLLATION_NAME, SQL_PATH, DEFAULT_ENCRYPTION), and
        ``CREATE DATABASE``/``CREATE SCHEMA`` has no ``COMMENT`` clause. (MariaDB
        added ``CREATE DATABASE ... COMMENT`` in 10.5.0, but this connector's
        extract_schema.sql targets standard MySQL's information_schema, not a
        MariaDB-specific extension.) So there's no ``remarks``-equivalent field
        for this mapper to read, unlike table/view/column/procedure below.
        """
        db_name = record.get(
            "catalog_name",
            record.get("database_name", record.get("datname", DATABASE_PLACEHOLDER)),
        )
        schema_name = record.get("schema_name", "")
        db_qn = _database_qn(db_name, connection_qn)
        asset = Schema.creator(name=schema_name, database_qualified_name=db_qn)
        asset.table_count = record.get("table_count", 0)
        asset.views_count = record.get("views_count", 0)
        asset.tenant_id = TENANT_ID
        asset.status = "ACTIVE"
        return _asset_to_dict(asset)

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

        db_qn = _database_qn(db_name, connection_qn)
        schema_qn = _schema_qn(schema_name, db_qn)

        is_view = table_kind in ("VIEW", "SYSTEM VIEW")
        asset_cls = View if is_view else Table
        asset = asset_cls.creator(name=table_name, schema_qualified_name=schema_qn)

        asset.column_count = record.get("column_count", 0)
        asset.size_bytes = record.get("size_bytes", 0)
        asset.tenant_id = TENANT_ID
        asset.status = "ACTIVE"
        # TABLE_COMMENT (extract_table.sql aliases it "remarks"); empty when the
        # source table/view has no comment set. Applies to both Table and View —
        # 'description' is a generic Asset-level field, not View-specific.
        asset.description = record.get("remarks", "") or ""

        # Table-specific fields (View has no is_partitioned/partition_count/row_count/
        # sub_type on the pyatlan_v9 model — isinstance narrows for the type checker)
        if isinstance(asset, Table):
            asset.row_count = record.get("row_count", 0)
            asset.sub_type = "TABLE"
            asset.is_partitioned = bool(record.get("is_partition", False))
            asset.partition_count = record.get("partition_count", 0)

        # View-specific fields
        if isinstance(asset, View):
            view_body = record.get("view_definition", "") or ""
            if view_body:
                # Prepend CREATE VIEW so QI/gudusoft can identify the target view
                # and generate view→table lineage edges. MySQL's VIEW_DEFINITION
                # stores only the SELECT body without the CREATE VIEW prefix.
                asset.definition = f"CREATE OR REPLACE VIEW {table_name} AS {view_body}"
            else:
                asset.definition = ""

        # Source timestamps
        source_created = _epoch_ms(record.get("create_time"))
        if source_created:
            asset.source_created_at = source_created

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
        asset.custom_attributes = custom

        entity = _asset_to_dict(asset)

        # QI reads column_mapping.defaultCatalogName / defaultSchemaName from the
        # top-level entity fields (not from nested attributes) and writes them to
        # each success.json row. Lineage-app uses these to resolve bare view/table
        # names (e.g. "akshaycat") to fully-qualified Atlas entity paths. This is a
        # live cross-app contract with QI/lineage-app, not a legacy-shape artifact —
        # pyatlan_v9's Asset model has no equivalent field, so it's added post-serialization.
        if is_view:
            entity["defaultCatalogName"] = db_name
            entity["defaultSchemaName"] = schema_name

        return entity

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

        db_qn = _database_qn(db_name, connection_qn)
        schema_qn = _schema_qn(schema_name, db_qn)

        is_view = table_type in ("VIEW", "SYSTEM VIEW")
        constraint = record.get("constraint_type", "")

        parent_cls = View if is_view else Table
        table_qn = _table_qn(table_name, schema_qn, is_view)

        asset = Column.creator(
            name=column_name,
            parent_qualified_name=table_qn,
            parent_type=parent_cls,
            order=record.get("ordinal_position", 0),
        )
        asset.data_type = (record.get("data_type") or "").upper()
        # COLUMN_COMMENT (extract_column.sql aliases it "remarks"); empty when unset.
        asset.description = record.get("remarks", "") or ""
        asset.is_nullable = record.get("is_nullable", "YES") == "YES"
        asset.is_partition = False
        asset.is_primary = constraint == "PRIMARY KEY"
        asset.is_foreign = constraint == "FOREIGN KEY"
        asset.max_length = (
            record.get("max_length", record.get("character_maximum_length", 0)) or 0
        )
        asset.numeric_scale = _coerce_numeric(
            record.get("numeric_scale", record.get("decimal_digits"))
        )
        asset.precision = int(_coerce_numeric(record.get("numeric_precision")))
        asset.tenant_id = TENANT_ID
        asset.status = "ACTIVE"

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
        asset.custom_attributes = custom

        return _asset_to_dict(asset)

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

        db_qn = _database_qn(catalog, connection_qn)
        schema_qn = _schema_qn(schema, db_qn)

        # Procedure.creator() derives the qualified name as
        # "{schema_qualified_name}/_procedures_/{name}" — matches the legacy format.
        # creator() rejects a blank definition (some procedures/functions have no
        # captured body, e.g. permission-restricted SHOW CREATE PROCEDURE), so pass
        # a placeholder to satisfy validation and overwrite it immediately after.
        asset = Procedure.creator(
            name=name, definition=definition or "-", schema_qualified_name=schema_qn
        )
        asset.definition = definition
        asset.sub_type = proc_type
        asset.tenant_id = TENANT_ID
        asset.status = "ACTIVE"
        # ROUTINE_COMMENT (extract_procedure.sql aliases it "remarks"); empty when unset.
        asset.description = record.get("remarks", "") or ""

        source_owner = record.get("source_owner", "") or ""
        if source_owner:
            asset.source_created_by = source_owner

        source_created = _epoch_ms(record.get("created"))
        if source_created:
            asset.source_created_at = source_created
        source_updated = _epoch_ms(record.get("last_altered"))
        if source_updated:
            asset.source_updated_at = source_updated

        return _asset_to_dict(asset)

    def _guard_complete_extraction(
        self, base_result: Any, transformed_dir: str | None = None
    ) -> None:
        """Fail fast if extraction produced a per-asset-type-partial artifact.

        A child asset type (column) must never reach publish without its parent
        structural types (database/schema/table); otherwise Atlas rejects every
        orphaned child with ATLAS-404-00-00A and the publish batch fails.

        Checks two views of the run and raises ``IncompleteExtractionError``
        (naming the missing parents) if either flags an orphaned descendant:

        * the per-type record counts on the SDK ``ExtractionOutput`` — catches a
          parent whose extraction produced no rows; and
        * when ``transformed_dir`` is given, the ``transformed/<type>/entities.json``
          files actually on disk — catches the case where a parent *was*
          extracted (non-zero count) but its transformed output never landed in
          the prefix that publish consumes.

        See ``completeness.py``.
        """
        counts = {
            "database": getattr(base_result, "databases_extracted", 0) or 0,
            "schema": getattr(base_result, "schemas_extracted", 0) or 0,
            "table": getattr(base_result, "tables_extracted", 0) or 0,
            "column": getattr(base_result, "columns_extracted", 0) or 0,
        }
        missing = find_incomplete_levels(counts)
        artifact = None
        if transformed_dir is not None:
            artifact = transformed_level_presence(transformed_dir)
            # Union both violation lists, preserving hierarchy order.
            missing = list(dict.fromkeys(missing + find_incomplete_levels(artifact)))
        if not missing:
            return
        logger.error(
            "Incomplete extraction artifact — missing parent types %s while a "
            "descendant type was extracted (counts=%s, artifact=%s). Refusing to "
            "publish a partial artifact that would orphan children in Atlas "
            "(ATLAS-404).",
            missing,
            counts,
            artifact,
        )
        raise IncompleteExtractionError(
            message=(
                "Extraction produced a partial artifact: missing parent asset "
                f"types {missing} while a descendant type was extracted "
                f"(counts={counts}, artifact_present={artifact}); refusing to "
                "publish to avoid orphaned entities (ATLAS-404)."
            )
        )

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
                ExtractionTaskInput, input, cred_ref=cred_ref
            )
            # Two-phase per the SDK contract: extract writes raw JSONL and
            # returns an ExtractionTaskOutput carrying a durable
            # FileReference; transform consumes that ref via TransformInput.
            # The activity interceptor handles the upload-on-output +
            # materialise-on-input handshake automatically, so the transform
            # runs correctly even when scheduled on a different worker pod
            # than the extract.
            #
            # The activity interceptor persists these FileReferences to
            # infra.storage (objectstore) for task-to-task durability.
            # The explicit App.upload() below handles the final hand-off
            # of the full transformed/ directory to upstream_storage (S3).
            proc_extract_result = await self.extract_procedures(proc_input)
            proc_transform_input = self._build_transform_input(
                proc_input, proc_extract_result.raw_file
            )
            await self.transform_procedures(proc_transform_input)

        # SqlApp.run() exposes its resolved local base path via output_path so
        # subclasses can derive additional prefixes without re-calling workflow.info().
        base = base_result.output_path
        connection_qn = base_result.connection_qualified_name

        # ATLAS-404 guard (RCA northwesternmutual-prod, 2026-07-15). The
        # extract→transform→publish handoff must never ship a per-asset-type
        # partial artifact: the failed run's transformed/ prefix held only
        # column/entities.json (1142 columns) with NO database/schema/table, so
        # every column 404'd in Atlas (typeName='Table' … not found) and the
        # whole publish batch failed. (Both failed onboarding runs were on
        # scale-to-zero cold-started pods and self-healed on a warm-pod retry
        # that re-extracted the complete set — cold-start is the observed
        # context; the exact write-loss mechanism is not yet confirmed.) Verify
        # completeness against both the extraction counts and the transformed/
        # artifact actually on disk, and fail loudly so Temporal retries with a
        # complete re-extract instead of shipping a doomed columns-only publish.
        self._guard_complete_extraction(
            base_result, transformed_dir=os.path.join(base, "transformed")
        )

        # Explicit upload to Atlan's upstream object store (atlan-objectstore / S3).
        # The activity interceptor persists FileReferences to infra.storage
        # (objectstore / deployment store) for task-to-task durability only.
        # System apps (publish, qi, lineage-app) read from upstream_storage, so the
        # final hand-off must be an explicit App.upload() that routes through it.
        await self.upload(
            UploadInput(
                local_path=os.path.join(base, "transformed"),
                storage_path=base_result.transformed_data_prefix,
                raise_on_empty=True,
            )
        )

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
