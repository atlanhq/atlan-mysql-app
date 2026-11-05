# AUTO-GENERATED from contract/app.pkl — DO NOT EDIT MANUALLY.
# To regenerate: pkl eval -m . contract/app.pkl
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
    redact_sql_text: str = "false"
    """Replaces string and numeric literals in extracted SQL definitions with placeholders, in memory, before anything is written to disk. SQL that can't be parsed is kept as-is. Query structure and lineage are preserved. Note: Increases extraction runtime."""
    preflight_check: str = ""
    output_dir: str = ""
    """Directory for output JSONL files."""
    checkpoint_dir: str = ""
    """Directory for checkpoint database. If provided, enables incremental extraction."""
    load_to_atlan: bool = True
    """If True, load extracted metadata to Atlan via publish-app."""
    publish_dry_run: bool = False
    """When True, skip the Atlas publish step (executor_enabled=False)."""
