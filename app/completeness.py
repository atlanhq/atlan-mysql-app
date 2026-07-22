"""Extraction-completeness guard (ATLAS-404 prevention).

RCA northwesternmutual-prod / mysql (2026-07-15): on a scale-to-zero cold start
(the app logged ``Dapr sidecar ... not fully initialized; proceeding without the
full-component wait``) the extract -> transform -> publish handoff advanced with
only a *partial* set of per-asset-type outputs written. The failed run's
transformed prefix contained only ``column/entities.json`` — no ``database``,
``schema``, ``table`` or ``view`` — with an otherwise-complete 1142 columns.
Publishing that partial artifact orphaned every column, so Atlas rejected each
one with ATLAS-404-00-00A ("Referenced entity ... typeName='Table' ... is not
found") and the whole publish batch failed (1142 failures). A sibling connection
in the same hour lost a different subset (only ``table``/``view``), so the
missing set is non-deterministic.

The pipeline had no invariant that a child asset type must never be handed to
publish without its ancestor structural types. This module supplies that
invariant so ``run()`` can fail loudly on an incomplete artifact — Temporal then
retries and a warm-pod retry re-extracts the complete set (exactly how the
incident self-healed) instead of shipping a doomed columns-only publish.
"""

from __future__ import annotations

import os
from pathlib import Path

# Ordered parent -> child asset-type hierarchy for a SQL source. Presence of any
# level implies every ancestor level must also be present in the same run: a
# column has a parent table, a table has a parent schema, a schema has a parent
# database. (MySQL emits both tables and views into the ``table`` stream, so a
# column's parent is always represented under ``table``.)
_HIERARCHY: tuple[str, ...] = ("database", "schema", "table", "column")


def find_incomplete_levels(counts: dict[str, int]) -> list[str]:
    """Return ancestor asset types missing while a descendant type is present.

    ``counts`` maps an asset type (``database`` / ``schema`` / ``table`` /
    ``column``) to the number of records extracted this run; missing keys count
    as ``0``. A level is a violation when its count is ``0`` while some
    *descendant* level's count is ``> 0`` — i.e. children were produced but a
    parent was not, so publishing would orphan those children in Atlas.

    Returns the violating ancestor types in hierarchy order. An empty list means
    the artifact is complete, or legitimately empty (no descendants extracted at
    all — e.g. a connection with nothing to crawl, or tables that genuinely have
    no columns).
    """
    violations: list[str] = []
    for index, level in enumerate(_HIERARCHY):
        if counts.get(level, 0) > 0:
            continue
        has_descendant = any(
            counts.get(descendant, 0) > 0 for descendant in _HIERARCHY[index + 1 :]
        )
        if has_descendant:
            violations.append(level)
    return violations


def transformed_level_presence(
    transformed_dir: str | os.PathLike[str],
) -> dict[str, int]:
    """Presence of each level's ``transformed/<level>/entities.json`` on disk.

    Returns a ``{level: 1 or 0}`` map suitable for :func:`find_incomplete_levels`
    — ``1`` when the level's ``entities.json`` exists and is non-empty, else
    ``0``. This inspects the *actual artifact* the publish step consumes, so it
    catches the case where a level was reported as extracted (non-zero count)
    but its transformed output never landed in the prefix. A missing prefix
    directory yields all-zeros (never a false positive: with no descendant
    present, nothing is flagged).
    """
    base = Path(transformed_dir)
    presence: dict[str, int] = {}
    for level in _HIERARCHY:
        entities = base / level / "entities.json"
        try:
            present = entities.is_file() and entities.stat().st_size > 0
        except OSError:
            present = False
        presence[level] = 1 if present else 0
    return presence
