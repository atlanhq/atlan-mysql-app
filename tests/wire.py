"""Serialise a mapper's return value the way the SDK does at runtime.

``SqlApp._transform_entity`` hands whatever ``map_<entity>()`` returned to
:func:`application_sdk.common.asset_serialization.entity_bytes` and writes the
resulting JSONL line. The mappers return ``pyatlan_v9`` assets, so a test that
asserts on the wire shape has to go through that same seam — asserting on the
asset's Python attributes instead would check the app's inputs to serialisation
rather than the entity publish actually receives.

:func:`wire` is deliberately a thin wrapper over the SDK call and nothing else:
a second serialiser written for the tests is a second wire format, and the one
it agrees with would be itself. :func:`rels_of` is a *reader* over that same
output, not a second serialiser — it exists so envelope-position changes on the
SDK side do not have to be chased through every ref assertion in the suite.
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


def rels_of(entity: dict[str, Any]) -> dict[str, Any]:
    """Relationship refs, from wherever the envelope puts them (FND-2137).

    The SDK flattens refs into ``attributes`` from 3.36.0; before that they sat
    under a top-level ``relationshipAttributes`` key. These tests assert the refs
    are *correct*, which holds in either envelope. Which envelope is in force is
    asserted once, by ``test_refs_live_in_exactly_one_place`` — so widening here
    does not lose that coverage.

    A widening, not a swap: an empty-or-absent ``relationshipAttributes`` falls
    through to ``attributes``, so the flattened envelope reads the same whether
    the SDK drops the key or leaves it behind empty.
    """
    return entity.get("relationshipAttributes") or entity.get("attributes", {})
