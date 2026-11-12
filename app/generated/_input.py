# AUTO-GENERATED from contract/app.pkl — DO NOT EDIT MANUALLY.
# To regenerate: pkl eval -m . contract/app.pkl
from __future__ import annotations

from typing import ClassVar

from application_sdk.templates.contracts import ExtractionInput

# ExtractionInput declares these fields only from atlan-application-sdk
# 3.39.1. On an older SDK the form values would be dropped, so fail
# at import instead.
_SDK_FLOOR_FIELDS = {"exclude_table_regex"}
if not _SDK_FLOOR_FIELDS <= ExtractionInput.model_fields.keys():
    raise ImportError("This input contract requires atlan-application-sdk>=3.39.1")


class AppInputContract(ExtractionInput):
    _config_hash_exclude: ClassVar[set[str]] = {
        "output_dir",
        "checkpoint_dir",
        "load_to_atlan",
        "publish_dry_run",
    }

    preflight_check: str = ""
    output_dir: str = ""
    """Directory for output JSONL files."""
    checkpoint_dir: str = ""
    """Directory for checkpoint database. If provided, enables incremental extraction."""
    load_to_atlan: bool = True
    """If True, load extracted metadata to Atlan via publish-app."""
    publish_dry_run: bool = False
    """When True, skip the Atlas publish step (executor_enabled=False)."""
