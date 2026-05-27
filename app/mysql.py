"""MySQLApp — v3 SQL connector for MySQL databases.

Extends SqlApp with MySQL-specific SQL queries and asset mappers.
"""

from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
from application_sdk.app import task
from application_sdk.contracts.base import Output
from application_sdk.credentials import CredentialResolver
from application_sdk.credentials.ref import CredentialRef
from application_sdk.execution._temporal.activity_utils import get_object_store_prefix
from application_sdk.infrastructure.context import get_infrastructure
from application_sdk.templates.contracts.sql_metadata import (
    ExtractionInput,
    ExtractionTaskInput,
    ExtractionTaskOutput,
)
from application_sdk.templates.sql_app import SqlApp
from pydantic import ConfigDict

from app.clients import SQLClient
from app.constants import DATABASE_PLACEHOLDER, TENANT_ID
from app.handlers.mysql import (  # noqa: F401 — SDK discovers {AppClass}Handler by convention
    MySQLAppHandler,
)
from app.utils import (
    extract_control_config,
    resolve_excluded_schemas,
    resolve_information_schema,
)

_logger = logging.getLogger(__name__)

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


class MySQLExtractionInput(ExtractionInput, allow_unbounded_fields=True):  # type: ignore[call-arg]
    """MySQL workflow input — adds typed control-config fields.

    REQ-925: the base ``ExtractionInput`` declares ``model_config =
    ConfigDict()`` (pydantic-v2 default ``extra='ignore'``), so when the
    AE payload arrives with ``control_config_strategy`` and
    ``control_config`` fields, pydantic **silently drops** them at the
    model boundary.
    """

    model_config = ConfigDict(extra="allow")

    control_config_strategy: str = "default"
    """``"custom"`` enables ``control_config`` overrides; anything else
    (including absent) preserves the canonical ``information_schema``
    code path."""

    control_config: str | dict[str, Any] = ""
    """JSON-encoded string or dict of feature-flag overrides.
    Supports: ``clonedInformationSchema`` (mirror-schema name)."""


class MySQLExtractionTaskInput(ExtractionTaskInput, allow_unbounded_fields=True):  # type: ignore[call-arg]
    """MySQL task input — adds typed control-config fields.

    REQ-925 follow-up: each ``@task`` activity runs on a FRESH
    ``app_instance = app_cls()`` (see SDK ``app/base.py:1478``). Stash-on-
    ``self`` from ``run()`` (the workflow worker) is invisible to the
    activity worker. Control-config must therefore travel ON THE INPUT
    OBJECT into each activity.

    Pydantic deserialisation on the activity side uses the @task method's
    declared annotation. If the activity signature says
    ``ExtractionTaskInput`` (extra='ignore' by default), the
    ``control_config*`` fields are stripped at the boundary even when
    workflow-side serialisation includes them. So:

    1. This subclass declares the fields explicitly + sets
       ``allow_unbounded_fields=True`` to silence the SDK's payload-safety
       check on ``dict[str, Any]``.
    2. ``MySQLApp`` overrides the 5 extract @task method signatures to
       declare ``MySQLExtractionTaskInput`` — only then will the activity-
       side pydantic round-trip preserve the fields.
    3. ``MySQLApp.build_task_input`` overrides the SDK staticmethod to
       construct ``MySQLExtractionTaskInput`` populated from the workflow
       input (copying ``control_config_strategy`` + ``control_config``).
    """

    model_config = ConfigDict(extra="allow")

    control_config_strategy: str = "default"
    control_config: str | dict[str, Any] = ""


class MySQLApp(SqlApp):
    """MySQL metadata extraction App.

    Extends SqlApp with:
    - MySQL-specific SQL queries from app/sql/ files
    - Asset mapper functions for databases, schemas, tables, columns, views
    - SQLClient with basic + IAM user + IAM role authentication
    - Optional mirror-schema override (``clonedInformationSchema`` in
      Custom Control Config) for customers whose security policy forbids
      ``SELECT`` on ``information_schema``. See REQ-925 + ``app/utils.py``.
    """

    name: ClassVar[str] = "mysql"

    sql_client_class: ClassVar = SQLClient  # type: ignore[assignment]

    # SQL templates from app/sql/ files. The literal ``{information_schema}``
    # placeholder is preserved here — runtime substitution happens in
    # ``_prepare_sql`` below, using control-config carried on the workflow
    # input. This keeps the class-level shape SDK-compatible (SqlApp reads
    # these as ClassVar strings) while still allowing per-run schema overrides.
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

    def _prepare_sql(self, sql: str, input: Any) -> str:  # type: ignore[override]
        """Substitute SDK filter placeholders and the MySQL mirror-schema.

        Runs the base ``SqlApp._prepare_sql`` first (which handles
        ``{normalized_exclude_regex}``, ``{normalized_include_regex}`` and
        ``{temp_table_regex_sql}``) and then resolves the connector-specific
        placeholders — ``{information_schema}`` (which catalog to query) and
        ``{excluded_schemas}`` (which schemas to filter out, including the
        mirror itself so its pass-through views don't surface as user
        assets). Both pull from the same control-config carried on the
        input. Backward compatible: when no config is supplied, the
        placeholders resolve to the canonical ``information_schema`` and
        the original 4-schema exclusion list, and output SQL is
        byte-identical to the pre-REQ-925 behavior.

        Reads control-config FROM the input — ``input`` here is a
        ``MySQLExtractionTaskInput`` populated by our override of
        ``build_task_input``. Stash-on-self does NOT work because each
        ``@task`` activity runs on a fresh ``app_instance``
        (``application_sdk/app/base.py:1478``); the workflow-side
        ``self._control_config`` set in ``run()`` is invisible to
        activities. Threading the config through the task input is the
        only contract Temporal preserves across the worker boundary.
        """
        prepared = super()._prepare_sql(sql, input)
        control_config = extract_control_config(input)
        prepared = resolve_information_schema(prepared, control_config)
        return resolve_excluded_schemas(prepared, control_config)

    @staticmethod
    def build_task_input(input_cls, src, *, cred_ref=None):  # type: ignore[override]
        """Construct a ``MySQLExtractionTaskInput`` populated from ``src``.

        Overrides the SDK staticmethod (``SqlApp.build_task_input``) so the
        extract tasks receive a task input that carries
        ``control_config_strategy`` / ``control_config`` (REQ-925).
        Falls back to the SDK base implementation when the caller asks for
        a different task-input class — preserves backward compat for any
        helper that explicitly passes ``ExtractionTaskInput`` (or another
        subclass) without expecting MySQL's extras.
        """
        # Always upgrade ExtractionTaskInput requests to the MySQL subclass
        # so control-config travels into the activities. The SDK's
        # ``SqlApp.run()`` calls ``build_task_input(ExtractionTaskInput, ...)``
        # — that's the path we need to intercept.
        if input_cls is ExtractionTaskInput or issubclass(
            input_cls, MySQLExtractionTaskInput
        ):
            return MySQLExtractionTaskInput(
                workflow_id=src.workflow_id,
                connection=src.connection,
                credential_guid=src.credential_guid,
                credential_ref=cred_ref,
                output_prefix=src.output_prefix,
                output_path=src.output_path,
                exclude_filter=src.exclude_filter,
                include_filter=src.include_filter,
                temp_table_regex=src.temp_table_regex,
                source_tag_prefix=getattr(src, "source_tag_prefix", ""),
                # Carry control-config onto the typed fields of the subclass.
                # ``getattr`` because ``src`` may be the SDK base class in
                # tests / call sites that haven't been migrated.
                control_config_strategy=getattr(
                    src, "control_config_strategy", "default"
                ),
                control_config=getattr(src, "control_config", ""),
            )
        # Fall back to the SDK base implementation for any other task
        # class the caller explicitly requested.
        return SqlApp.build_task_input(input_cls, src, cred_ref=cred_ref)

    # ── @task overrides — declare the MySQL task-input subclass so
    # pydantic preserves ``control_config*`` on the activity side. The
    # SDK's parent @task methods declare ``ExtractionTaskInput`` (default
    # ``extra='ignore'``) and would strip the fields at activity-side
    # deserialisation. Delegating to the SDK's per-entity helper keeps
    # the bodies identical to the SDK base implementation.

    @task(
        timeout_seconds=1800, heartbeat_timeout_seconds=120, auto_heartbeat_seconds=30
    )
    async def extract_databases(  # type: ignore[override]
        self, input: MySQLExtractionTaskInput
    ) -> ExtractionTaskOutput:
        return await self._extract_entity(
            entity_type="database",
            sql_template=self.fetch_database_sql,
            input=input,
        )

    @task(
        timeout_seconds=1800, heartbeat_timeout_seconds=120, auto_heartbeat_seconds=30
    )
    async def extract_schemas(  # type: ignore[override]
        self, input: MySQLExtractionTaskInput
    ) -> ExtractionTaskOutput:
        return await self._extract_entity(
            entity_type="schema",
            sql_template=self.fetch_schema_sql,
            input=input,
        )

    @task(
        timeout_seconds=1800, heartbeat_timeout_seconds=120, auto_heartbeat_seconds=30
    )
    async def extract_tables(  # type: ignore[override]
        self, input: MySQLExtractionTaskInput
    ) -> ExtractionTaskOutput:
        return await self._extract_entity(
            entity_type="table",
            sql_template=self.fetch_table_sql,
            input=input,
        )

    @task(
        timeout_seconds=1800, heartbeat_timeout_seconds=120, auto_heartbeat_seconds=30
    )
    async def extract_columns(  # type: ignore[override]
        self, input: MySQLExtractionTaskInput
    ) -> ExtractionTaskOutput:
        return await self._extract_entity(
            entity_type="column",
            sql_template=self.fetch_column_sql,
            input=input,
        )

    @task(
        timeout_seconds=1800, heartbeat_timeout_seconds=120, auto_heartbeat_seconds=30
    )
    async def extract_procedures(  # type: ignore[override]
        self, input: MySQLExtractionTaskInput
    ) -> ExtractionTaskOutput:
        return await self._extract_entity(
            entity_type="extras-procedure",
            sql_template=self.fetch_procedure_sql,
            input=input,
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

        entity: dict[str, Any] = {
            "typeName": type_name,
            "tenantId": TENANT_ID,
            "status": "ACTIVE",
            "attributes": attrs,
            "customAttributes": custom,
        }

        # QI reads column_mapping.defaultCatalogName / defaultSchemaName from the
        # top-level entity fields (not from nested attributes) and writes them to
        # each success.json row. Lineage-app uses these to resolve bare view/table
        # names (e.g. "akshaycat") to fully-qualified Atlas entity paths.
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

    def _materialize_mirror_into_input(self, creds: dict[str, Any], input: Any) -> None:
        """REQ-925: inject ``extra.clonedInformationSchema`` from a resolved
        credentials dict into ``input.control_config`` so ``_prepare_sql``
        sees the mirror schema.

        Called from :meth:`_init_sql_client` — that override runs inside
        each extract activity (not in the workflow), so it's safe to do
        credential resolution and ``input`` mutation here without tripping
        Temporal's workflow-determinism guards.

        Precedence: an operator-set ``control_config.clonedInformationSchema``
        (from Advanced Config JSON) wins over the credential value. We try
        three credential shapes because the resolver-side raw dict can
        deliver the extras either nested or flat:

          1. ``creds["extra"]["clonedInformationSchema"]`` (nested)
          2. ``creds["extra.clonedInformationSchema"]`` (flat dotted)
          3. ``creds["clonedInformationSchema"]`` (top-level fallback)
        """
        try:
            existing = extract_control_config(input) or {}
        except Exception:
            existing = {}
        if existing.get("clonedInformationSchema"):
            return  # operator-supplied JSON wins

        mirror: Any = None
        if isinstance(creds, dict):
            nested = creds.get("extra")
            if isinstance(nested, dict):
                mirror = nested.get("clonedInformationSchema")
            if mirror is None:
                mirror = creds.get("extra.clonedInformationSchema")
            if mirror is None:
                mirror = creds.get("clonedInformationSchema")

        if not isinstance(mirror, str) or not mirror.strip():
            return
        mirror = mirror.strip()
        _logger.info(
            "REQ-925: materializing clonedInformationSchema=%s into "
            "control_config from credential extras",
            mirror,
        )

        # Mutate input in place. We're inside the activity here — ``input``
        # is the task-input snapshot Temporal handed us; mutations stay
        # local to this activity's execution.
        try:
            input.control_config_strategy = "custom"
            if isinstance(input.control_config, dict):
                input.control_config["clonedInformationSchema"] = mirror
            else:
                input.control_config = {"clonedInformationSchema": mirror}
        except Exception as exc:  # pragma: no cover — fail-soft on frozen models
            _logger.warning("REQ-925: failed to mutate task input with mirror: %s", exc)

    async def _init_sql_client(self, input: Any) -> Any:  # type: ignore[override]
        """Override SDK's ``_init_sql_client`` so we can plumb
        ``extra.clonedInformationSchema`` from the resolved credential
        into ``input.control_config`` before any extract SQL is prepared.

        The SDK's base method (``application_sdk/templates/sql_app.py:898``)
        resolves the credential via ``CredentialResolver.resolve_raw`` and
        calls ``client.load(credentials=creds)``. We do the same here, but
        intercept the ``creds`` dict to extract the mirror schema name and
        materialize it into ``input.control_config`` — which downstream
        ``_prepare_sql`` calls then pick up via ``extract_control_config``.

        This runs inside each extract @task activity (per-activity
        credential resolution is the SDK's existing pattern, so it's
        already activity-context-safe — no Temporal determinism violation).
        Previously we attempted this in ``MySQLApp.run()`` (workflow
        context), which failed because ``CredentialResolver`` uses
        ``threading.local`` internally; the activity context has no such
        restriction.
        """
        if self.sql_client_class is None:
            from application_sdk.templates.sql_app_errors import (  # noqa: PLC0415
                SqlClientClassNotSetError,
            )

            raise SqlClientClassNotSetError()

        client = self.sql_client_class()
        creds: dict[str, Any] = {}

        ref: CredentialRef | None = getattr(input, "credential_ref", None)
        if ref is None and getattr(input, "credential_guid", None):
            from application_sdk.credentials import (  # noqa: PLC0415
                legacy_credential_ref,
            )

            ref = legacy_credential_ref(input.credential_guid)

        if ref is not None:
            try:
                infra = get_infrastructure()
                secret_store = infra.secret_store if infra else None
                if secret_store is not None:
                    resolver = CredentialResolver(secret_store)
                    creds = await resolver.resolve_raw(ref) or {}
            except Exception as exc:
                _logger.warning(
                    "REQ-925: credential resolve_raw failed in _init_sql_client: %s",
                    exc,
                )

        # REQ-925: inject the mirror schema name into input.control_config
        # so the upcoming _prepare_sql call(s) in this activity see it.
        self._materialize_mirror_into_input(creds, input)

        await client.load(credentials=creds)
        return client

    async def _materialize_credential_mirror_into_control_config(
        self, input: MySQLExtractionInput
    ) -> None:
        """Legacy workflow-side helper — kept as a no-op for backwards
        compat with any orchestration that still calls it. The real
        materialization now happens in :meth:`_init_sql_client` (activity
        context). Calling this from a workflow method is safe (no I/O).
        """
        # REQ-925 history: this used to do credential resolution inline in
        # the workflow, but Temporal's workflow-determinism guard blocks
        # ``CredentialResolver.resolve_raw`` (it uses ``threading.local``).
        # Logic was moved to ``_init_sql_client`` which runs in activity
        # context. This stub is kept to avoid breaking any orchestrator
        # that imports/calls the symbol.
        return

    async def run(  # type: ignore[override]
        self, input: MySQLExtractionInput
    ) -> MySQLExtractionOutput:
        """MySQL extraction: standard assets + procedures + lineage pipeline outputs.

        1. Standard fetch/transform/upload (databases, schemas, tables, columns).
           ``control_config`` flows into each activity via ``MySQLExtractionTaskInput``
           constructed by our ``build_task_input`` override — the SDK's
           ``run()`` calls ``self.build_task_input(ExtractionTaskInput, input, ...)``
           and gets the MySQL subclass back, carrying the typed fields.
        2. Stored procedures — writes ``extras-procedure/`` so the QI SQL parser
           derives procedure-level lineage from ``definition`` fields.
        3. Returns extended output with view_lineage_output_prefix,
           lineage_stage_prefix, and storage_bucket so the manifest DAG can
           chain qi → lineage-app → lineage-publish nodes (Athena pattern).
        """
        # REQ-925 follow-up: thread the credential's
        # ``extra.clonedInformationSchema`` into ``input.control_config`` so
        # workflow-runtime extract activities pick up the mirror schema. The
        # handler endpoints (test_auth / preflight / fetch_metadata) read
        # from ``input.credentials`` directly, but the @task activities
        # receive ``MySQLExtractionTaskInput`` which only carries
        # ``control_config`` across the worker boundary. Mutating the
        # workflow input here lets our ``build_task_input`` override
        # snapshot the synthesized value via the existing
        # ``control_config_strategy`` / ``control_config`` pathway — no
        # changes to the task-input schema needed.
        await self._materialize_credential_mirror_into_control_config(input)

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
            # than the extract (BLDX-1281).
            #
            # No explicit ``upload_to_atlan`` call is needed — both
            # ``extract_procedures`` and ``transform_procedures`` emit
            # ``FileReference`` objects with pre-set canonical
            # ``storage_path`` keys (``<run_prefix>/raw/extras-procedure/
            # records.json`` / ``<run_prefix>/transformed/extras-procedure/
            # entities.json``), and the activity interceptor has already
            # uploaded each one to that key by the time the activity
            # returns. Publish reads from those same canonical prefixes,
            # so the data is already in the object store waiting for it.
            proc_extract_result = await self.extract_procedures(proc_input)
            proc_transform_input = self._build_transform_input(
                proc_input, proc_extract_result.raw_file
            )
            await self.transform_procedures(proc_transform_input)

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
