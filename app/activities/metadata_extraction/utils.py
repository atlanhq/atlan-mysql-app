import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INFORMATION_SCHEMA_PREFIX = "information_schema."


def resolve_cloned_information_schema(
    workflow_args: Dict[str, Any],
    default_sql: Optional[str],
) -> Optional[str]:
    """Resolve {cloned_information_schema} placeholders in SQL.

    Reads 'control-config-strategy' and 'control-config' from workflow_args.
    If a 'clonedInformationSchema' key is configured, replaces the placeholder
    with '<schema_name>.'. Otherwise defaults to 'information_schema.'.

    Also resolves {cloned_schema_exclusion} for NOT IN list additions.

    Args:
        workflow_args: Workflow arguments dict containing config.
        default_sql: SQL template string with placeholders.

    Returns:
        Resolved SQL string, or None if default_sql is None/empty.
    """
    if not default_sql:
        return None

    info_schema_prefix = DEFAULT_INFORMATION_SCHEMA_PREFIX
    schema_exclusion = ""

    control_config_strategy = workflow_args.get("control-config-strategy")
    control_config = workflow_args.get("control-config")

    if control_config_strategy == "custom" and control_config:
        if isinstance(control_config, str):
            try:
                control_config = json.loads(control_config)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse control-config JSON, using default information_schema"
                )
                control_config = {}

        cloned_schema = (control_config or {}).get("clonedInformationSchema")
        if cloned_schema:
            if not re.match(r"^[a-zA-Z0-9_]+$", cloned_schema):
                logger.error(
                    "Invalid clonedInformationSchema name %r; "
                    "must be alphanumeric/underscore only. Using default.",
                    cloned_schema,
                )
                cloned_schema = None
        if cloned_schema:
            info_schema_prefix = f"{cloned_schema}."
            schema_exclusion = f", '{cloned_schema}'"

    resolved = default_sql.replace(
        "{cloned_information_schema}", info_schema_prefix
    )
    resolved = resolved.replace("{cloned_schema_exclusion}", schema_exclusion)
    return resolved
