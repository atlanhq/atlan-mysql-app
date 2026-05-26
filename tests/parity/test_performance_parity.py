"""Level 2B: Performance parity — compare v2 vs v3 execution characteristics.

Asset (record count) parity is enforced as a hard failure. Timing comparisons
are reported as warnings only — CI variance is too high to block parity on
wall clock or server-side duration alone.

Configure timing-warning threshold via env var:
  PARITY_DURATION_MULTIPLIER=2.0  (default: warn when v3 > 2x v2)

Run:
  uv run pytest tests/parity/test_performance_parity.py -v
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import pytest

try:
    from .parity_entities import (
        ENTITY_TO_TYPENAME,
        ENTITY_TYPES,
        RECORD_COUNT_FIELDS,
        RESULT_COUNT_FIELDS,
    )
except ImportError:
    from parity_entities import (
        ENTITY_TO_TYPENAME,
        ENTITY_TYPES,
        RECORD_COUNT_FIELDS,
        RESULT_COUNT_FIELDS,
    )

PARITY_DIR = Path(__file__).parent
OUTPUT_DIR = PARITY_DIR / "output"
DURATION_MULTIPLIER = float(os.environ.get("PARITY_DURATION_MULTIPLIER", "2.0"))


# ── Discovery ──────────────────────────────────────────────────────────────


def _discover_scenarios() -> list[str]:
    """Find scenarios that have timing data for both v2 and v3."""
    found = []
    if not OUTPUT_DIR.is_dir():
        return found
    for d in sorted(OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        golden_timing = d / "api_golden" / "timing.json"
        v3_timing = d / "api_v3" / "timing.json"
        if golden_timing.exists() and v3_timing.exists():
            found.append(d.name)
    return found


def _load_timing(scenario: str, version: str) -> dict:
    subdir = "api_golden" if version == "v2" else "api_v3"
    path = OUTPUT_DIR / scenario / subdir / "timing.json"
    if not path.exists():
        pytest.skip(f"No timing data: {path}")
    with open(path) as f:
        return json.load(f)


def _unique_counts(scenario: str, subdir: str) -> dict[str, int] | None:
    """Count unique qualifiedNames per entity from transformed JSONL.

    Returns None if the transformed dir is missing — caller falls back to
    raw row counts from timing.json.

    Records are bucketed by their ``typeName`` field across every
    ``*.jsonl`` in the dir, not by emitting filename. v2 packs Tables and
    Views into a single ``table.jsonl`` with mixed ``typeName`` values
    (Table, View); v3 splits them into separate files. Counting by
    ``typeName`` makes the comparison agnostic to that file-layout split.
    """
    base = OUTPUT_DIR / scenario / subdir
    if not base.is_dir():
        return None

    qns_by_type: dict[str, set[str]] = {tn: set() for tn in ENTITY_TO_TYPENAME.values()}
    for path in base.glob("*.jsonl"):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tn = rec.get("typeName")
                if tn not in qns_by_type:
                    continue
                qn = rec.get("attributes", {}).get("qualifiedName") or rec.get(
                    "uniqueAttributes", {}
                ).get("qualifiedName")
                if qn:
                    qns_by_type[tn].add(qn)

    return {
        RESULT_COUNT_FIELDS[entity]: len(qns_by_type[ENTITY_TO_TYPENAME[entity]])
        for entity in ENTITY_TYPES
    }


_SCENARIOS = _discover_scenarios()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestPerformanceParity:
    @pytest.mark.parametrize("scenario", _SCENARIOS)
    def test_wall_clock_within_bounds(self, scenario: str) -> None:
        v2 = _load_timing(scenario, "v2")
        v3 = _load_timing(scenario, "v3")

        v2_wc = v2.get("wall_clock_seconds")
        v3_wc = v3.get("wall_clock_seconds", 0)

        if v2_wc is None or v2_wc <= 0:
            pytest.skip(f"[{scenario}] v2 wall_clock not recorded, cannot compare")

        ratio = v3_wc / v2_wc
        if v3_wc > v2_wc * DURATION_MULTIPLIER:
            warnings.warn(
                f"[{scenario}] v3 wall clock {v3_wc:.1f}s > {DURATION_MULTIPLIER}x v2 {v2_wc:.1f}s "
                f"(ratio: {ratio:.2f}x, limit: {DURATION_MULTIPLIER}x)",
                stacklevel=2,
            )

    @pytest.mark.parametrize("scenario", _SCENARIOS)
    def test_execution_duration_within_bounds(self, scenario: str) -> None:
        v2 = _load_timing(scenario, "v2")
        v3 = _load_timing(scenario, "v3")

        v2_dur = v2.get("execution_duration_seconds")
        v3_dur = v3.get("execution_duration_seconds", 0)

        if v2_dur is None or v2_dur <= 0:
            pytest.skip(
                f"[{scenario}] v2 execution_duration not recorded, cannot compare"
            )

        ratio = v3_dur / v2_dur
        if v3_dur > v2_dur * DURATION_MULTIPLIER:
            warnings.warn(
                f"[{scenario}] v3 duration {v3_dur:.1f}s > {DURATION_MULTIPLIER}x v2 {v2_dur:.1f}s "
                f"(ratio: {ratio:.2f}x, limit: {DURATION_MULTIPLIER}x)",
                stacklevel=2,
            )

    @pytest.mark.parametrize("scenario", _SCENARIOS)
    def test_record_counts_match(self, scenario: str) -> None:
        # Compare unique qualifiedName counts from the transformed JSONL files
        # rather than raw row counts in timing.json. v2 (golden) emits duplicate
        # rows for some columns that participate in multiple FK / index
        # relationships; v3 dedupes to one row per qualifiedName. Comparing
        # uniques makes the assertion exact and free of v2's duplicate-row noise.
        v2_unique = _unique_counts(scenario, "golden")
        v3_unique = _unique_counts(scenario, "v3")

        if v2_unique is None or v3_unique is None:
            # No transformed JSONL on disk — fall back to timing.json raw counts.
            v2_counts = _load_timing(scenario, "v2")
            v3_counts = _load_timing(scenario, "v3")
            v2_unique = {f: v2_counts.get(f, 0) or 0 for f in RECORD_COUNT_FIELDS}
            v3_unique = {f: v3_counts.get(f, 0) or 0 for f in RECORD_COUNT_FIELDS}

        diffs = []
        for field in RECORD_COUNT_FIELDS:
            v2_val = v2_unique.get(field, 0)
            v3_val = v3_unique.get(field, 0)
            if v2_val != v3_val:
                diffs.append(
                    f"  {field}: v2={v2_val}, v3={v3_val} (delta: {v3_val - v2_val:+d})"
                )

        assert not diffs, f"[{scenario}] Record count mismatches:\n" + "\n".join(diffs)


class TestPerformanceReport:
    """Informational: prints a comparison table. Always passes."""

    def test_generate_performance_report(self) -> None:
        if not _SCENARIOS:
            pytest.skip("No scenarios with timing data")

        rows = []
        for scenario in _SCENARIOS:
            v2 = _load_timing(scenario, "v2")
            v3 = _load_timing(scenario, "v3")

            v2_wc = v2.get("wall_clock_seconds", 0)
            v3_wc = v3.get("wall_clock_seconds", 0)
            ratio = v3_wc / v2_wc if v2_wc > 0 else 0
            status = "OK" if ratio <= DURATION_MULTIPLIER else "WARN"

            rows.append((scenario, v2_wc, v3_wc, ratio, status))

        # Print report
        header = (
            f"{'Scenario':<30} | {'v2 dur':>8} | {'v3 dur':>8} | {'Ratio':>7} | Status"
        )
        sep = "-" * len(header)
        lines = ["\n", sep, "  Performance Parity Report", sep, header, sep]
        for scenario, v2_wc, v3_wc, ratio, status in rows:
            lines.append(
                f"{scenario:<30} | {v2_wc:>7.1f}s | {v3_wc:>7.1f}s | {ratio:>6.2f}x | {status}"
            )
        lines.append(sep)
        lines.append(f"  Threshold: {DURATION_MULTIPLIER}x")
        lines.append("")

        print("\n".join(lines))
