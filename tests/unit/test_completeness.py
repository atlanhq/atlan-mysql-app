"""Unit tests for the extraction-completeness guard (ATLAS-404 prevention).

RCA northwesternmutual-prod / mysql (2026-07-15): a scale-to-zero cold start let
the extract->transform->publish handoff advance with only a partial set of
per-asset-type outputs (e.g. only ``column/entities.json`` while
``database``/``schema``/``table`` were never written). Publishing that partial
artifact orphaned every column, so Atlas rejected each with ATLAS-404-00-00A
("Referenced entity typeName='Table' ... not found") and the whole publish batch
failed. ``find_incomplete_levels`` detects such an artifact so the run can fail
loudly instead of shipping a doomed columns-only publish.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.completeness import find_incomplete_levels, transformed_level_presence
from app.failures import IncompleteExtractionError
from app.mysql import MySQLApp


def _write_entities(transformed_dir, *levels: str, empty: str | None = None):
    """Create ``transformed/<level>/entities.json`` for each named level.

    ``empty`` names a level whose entities.json is written 0-byte (present but
    empty) to assert it is treated as absent.
    """
    for level in levels:
        d = transformed_dir / level
        d.mkdir(parents=True, exist_ok=True)
        (d / "entities.json").write_text("" if level == empty else '{"x":1}\n')


class TestFindIncompleteLevels:
    def test_complete_extraction_has_no_violations(self):
        counts = {"database": 1, "schema": 1, "table": 120, "column": 1142}
        assert find_incomplete_levels(counts) == []

    def test_columns_without_table_parent_flags_table(self):
        # The exact NWM sibling shape (bdbc358e): db+schema+columns, no tables.
        counts = {"database": 1, "schema": 5, "table": 0, "column": 140}
        assert find_incomplete_levels(counts) == ["table"]

    def test_columns_with_all_parents_missing_flags_every_ancestor(self):
        # The exact NWM failed run (6827a980): only columns were written.
        counts = {"database": 0, "schema": 0, "table": 0, "column": 1142}
        assert find_incomplete_levels(counts) == ["database", "schema", "table"]

    def test_missing_middle_level_only(self):
        counts = {"database": 1, "schema": 0, "table": 120, "column": 1142}
        assert find_incomplete_levels(counts) == ["schema"]

    def test_empty_extraction_is_not_a_violation(self):
        # A connection with nothing to crawl is legitimate, not incomplete.
        counts = {"database": 0, "schema": 0, "table": 0, "column": 0}
        assert find_incomplete_levels(counts) == []

    def test_tables_without_columns_is_legitimate(self):
        # Tables/views with zero columns extracted is a valid (empty) result,
        # never an orphan — only a *descendant* being present forces the parent.
        counts = {"database": 1, "schema": 1, "table": 120, "column": 0}
        assert find_incomplete_levels(counts) == []

    def test_missing_keys_treated_as_zero(self):
        # A columns-only artifact where parent keys are absent entirely.
        assert find_incomplete_levels({"column": 1142}) == [
            "database",
            "schema",
            "table",
        ]


class TestTransformedLevelPresence:
    """The on-disk artifact check catches case (b): parents were 'extracted'
    (counts > 0) but their transformed entities.json never landed in the prefix
    that publish consumes."""

    def test_columns_only_prefix_flags_all_parents(self, tmp_path):
        # The exact NWM failed artifact: only transformed/column/entities.json.
        _write_entities(tmp_path, "column")
        presence = transformed_level_presence(tmp_path)
        assert find_incomplete_levels(presence) == ["database", "schema", "table"]

    def test_complete_prefix_has_no_violations(self, tmp_path):
        _write_entities(tmp_path, "database", "schema", "table", "column")
        assert find_incomplete_levels(transformed_level_presence(tmp_path)) == []

    def test_missing_prefix_dir_is_not_a_false_positive(self, tmp_path):
        # Nothing written (or run() executing without a local FS) → all-zero →
        # no descendant present → no violation. Must never false-positive.
        assert find_incomplete_levels(transformed_level_presence(tmp_path)) == []

    def test_empty_entities_file_treated_as_absent(self, tmp_path):
        _write_entities(
            tmp_path, "database", "schema", "table", "column", empty="table"
        )
        assert find_incomplete_levels(transformed_level_presence(tmp_path)) == ["table"]


def _extraction_output(databases: int, schemas: int, tables: int, columns: int):
    """Minimal stand-in for the SDK ``ExtractionOutput`` returned by super().run()."""
    return SimpleNamespace(
        databases_extracted=databases,
        schemas_extracted=schemas,
        tables_extracted=tables,
        columns_extracted=columns,
    )


class TestGuardCompleteExtraction:
    @pytest.fixture
    def app(self):
        return MySQLApp()

    def test_raises_on_columns_only_artifact(self, app):
        # The exact NWM failed run: 1142 columns, no parents.
        result = _extraction_output(databases=0, schemas=0, tables=0, columns=1142)
        with pytest.raises(IncompleteExtractionError) as exc:
            app._guard_complete_extraction(result)
        # The error must name the missing parent types so it is actionable.
        assert "table" in str(exc.value)

    def test_raises_when_only_tables_missing(self, app):
        # The sibling connection: db+schema+columns, no tables.
        result = _extraction_output(databases=1, schemas=5, tables=0, columns=140)
        with pytest.raises(IncompleteExtractionError):
            app._guard_complete_extraction(result)

    def test_passes_on_complete_artifact(self, app):
        result = _extraction_output(databases=1, schemas=1, tables=120, columns=1142)
        # Must not raise.
        app._guard_complete_extraction(result)

    def test_passes_on_legitimately_empty_artifact(self, app):
        result = _extraction_output(databases=0, schemas=0, tables=0, columns=0)
        app._guard_complete_extraction(result)

    def test_raises_when_counts_complete_but_artifact_partial(self, app, tmp_path):
        # Case (b): extraction reported parents (counts > 0) but their
        # transformed entities.json never landed — only column/ is on disk.
        # The counts alone would pass; the on-disk artifact check must catch it.
        result = _extraction_output(databases=1, schemas=1, tables=120, columns=1142)
        _write_entities(tmp_path, "column")
        with pytest.raises(IncompleteExtractionError) as exc:
            app._guard_complete_extraction(result, transformed_dir=str(tmp_path))
        assert "table" in str(exc.value)

    def test_passes_when_counts_and_artifact_both_complete(self, app, tmp_path):
        result = _extraction_output(databases=1, schemas=1, tables=120, columns=1142)
        _write_entities(tmp_path, "database", "schema", "table", "column")
        app._guard_complete_extraction(result, transformed_dir=str(tmp_path))
