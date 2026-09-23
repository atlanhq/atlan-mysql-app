"""The extract node's args, as the Automation Engine sends them to ``run()``.

Read from the committed ``app/generated/manifest.json`` rather than written out
by hand, so a test built on this breaks when the manifest gains or renames an
arg the entrypoint does not receive. Every ``{{mustache}}`` value the caller
does not override is rendered empty, which is what an unset form field sends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_type_hints

from application_sdk.contracts.base import Input

from app.mysql import MySQLApp

_MANIFEST = Path(__file__).parent.parent / "app" / "generated" / "manifest.json"


def extract_input_type() -> type[Input]:
    """The type the SDK validates the extract payload against.

    Resolved the way the SDK resolves it — from ``run()``'s annotation — so a
    test using it fails if ``run()`` is re-annotated with a narrower contract.
    """
    return get_type_hints(MySQLApp.run)["input"]


def manifest_extract_args(**overrides: Any) -> dict[str, Any]:
    """The extract node's ``inputs.args``, rendered with *overrides*.

    An override for a key the manifest does not send (e.g. a test's
    ``credential_ref``) is added alongside.
    """
    manifest = json.loads(_MANIFEST.read_text())
    args: dict[str, Any] = manifest["dag"]["extract"]["inputs"]["args"]
    rendered: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and value.startswith("{{"):
            rendered[key] = ""
        else:
            rendered[key] = value
    return {**rendered, **overrides}
