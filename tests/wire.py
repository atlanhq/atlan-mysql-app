"""Serialise a mapper's return value the way the SDK does at runtime.

``SqlApp._transform_entity`` hands whatever ``map_<entity>()`` returned to
:func:`application_sdk.common.asset_serialization.entity_bytes` and writes the
resulting JSONL line. The mappers return ``pyatlan_v9`` assets, so a test that
asserts on the wire shape has to go through that same seam — asserting on the
asset's Python attributes instead would check the app's inputs to serialisation
rather than the entity publish actually receives.

Deliberately a thin wrapper over the SDK call and nothing else: a second
serialiser written for the tests is a second wire format, and the one it agrees
with would be itself.
"""

from __future__ import annotations

from typing import Any

import orjson
from application_sdk.common.asset_serialization import entity_bytes


def wire(asset: Any, *, connection_name: str = "") -> dict[str, Any]:
    """Return *asset* as the entity dict the transform step would write.

    Args:
        asset: A mapper's return value — a ``pyatlan_v9`` asset or a dict.
        connection_name: Stamped onto the asset when the mapper left it unset,
            exactly as ``_transform_entity`` does with the connection's display
            name. Empty (the default) skips the injection.
    """
    return orjson.loads(entity_bytes(asset, connection_name=connection_name))
