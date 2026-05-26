# AUTO-GENERATED from app.pkl — DO NOT EDIT MANUALLY.
# To regenerate: make generate
from __future__ import annotations
from typing import ClassVar
from application_sdk.templates.contracts import ExtractionInput


class AppInputContract(ExtractionInput):
    _config_hash_exclude: ClassVar[set[str]] = {
        "output_dir",
        "checkpoint_dir",
        "load_to_atlan",
        "publish_dry_run",
    }

    exclude_table_regex: str = ""
    """Regular expression to exclude temporary tables and views."""
    preflight_check: str = ""
    control_config_strategy: str = "default"
    """Controls custom feature flags for the crawler. Select Custom to enable the INFORMATION_SCHEMA mirror-schema flow for restricted-access deployments."""
    control_config: str = ""
    """Custom JSON config. To route all metadata queries through a customer-managed mirror schema, set: {"clonedInformationSchema": "<your-mirror-schema-name>"} — the connector will query <your-mirror-schema-name>.* instead of information_schema.*. Required when the connector user does not have SELECT on the native information_schema."""
    output_dir: str = ""
    """Directory for output JSONL files."""
    checkpoint_dir: str = ""
    """Directory for checkpoint database. If provided, enables incremental extraction."""
    load_to_atlan: bool = True
    """If True, load extracted metadata to Atlan via publish-app."""
    publish_dry_run: bool = False
    """When True, skip the Atlas publish step (executor_enabled=False)."""
