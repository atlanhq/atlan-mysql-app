#!/usr/bin/env python3
"""Build a Markdown summary of parity results for PR comments / step summary.

Reads the per-scenario normalized outputs from ``tests/parity/output/``:

    output/<scenario>/golden/<entity>.jsonl        # baseline (main)
    output/<scenario>/v3/<entity>.jsonl            # PR
    output/<scenario>/api_golden/timing.json       # baseline timing + counts
    output/<scenario>/api_v3/timing.json           # PR timing + counts

Also reads ``results/parity.xml`` (JUnit XML) if available for a pytest
pass/fail breakdown by test class.

Emits a single Markdown document to stdout containing:

  - Scenarios covered
  - Record counts (reported by /result)
  - Record counts (transformed)
  - Reconciled deltas — collapses v3's table→view promotion so the real
    missing/extra counts are visible
  - Attribute drift — shared qualifiedNames only, bucketed by attribute
    name and classified (known v3 improvement / live-DB variance /
    unexplained)
  - Entity diffs — raw added/removed qualifiedNames per scenario/entity
  - Execution duration comparison
  - Pytest results by class

Tolerates missing files — partially-complete runs still produce a useful
summary.

Usage::

    uv run python tests/parity/summarize.py [--output-dir tests/parity/output]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    from .parity_entities import ENTITY_TYPES, RESULT_COUNT_FIELDS
except ImportError:
    from parity_entities import ENTITY_TYPES, RESULT_COUNT_FIELDS

MAX_ITEMS = 20  # cap per-entity added/removed list in the summary
MAX_ATTR_ROWS = 25  # cap rows in attribute drift table

# Kept in sync with tests/parity/test_parity.py. Duplicated here to avoid
# importing test_parity (pytest side-effects). If those constants drift,
# update both places.
VOLATILE_FIELDS = {"lastSyncWorkflowName", "lastSyncRun", "lastSyncRunAt", "tenantId"}
KNOWN_V3_IMPROVEMENTS = {"isPrimary", "isForeign"}
LOOSE_COMPARE_FIELDS = {
    "schemaCount",
    "tableCount",
    "columnCount",
    "rowCount",
    "sizeBytes",
}
SYSTEM_DATABASES = {"mysql", "information_schema", "performance_schema", "sys"}
CANONICAL_CONNECTION_QN = "default/mysql/__PARITY__"


# ── I/O helpers ─────────────────────────────────────────────────────────────


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_timing(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _qns(records: list[dict]) -> set[str]:
    return {
        r.get("attributes", {}).get("qualifiedName", "")
        for r in records
        if r.get("attributes", {}).get("qualifiedName")
    }


def _by_qn(records: list[dict]) -> dict[str, dict]:
    return {
        r["attributes"]["qualifiedName"]: r
        for r in records
        if r.get("attributes", {}).get("qualifiedName")
    }


# ── Formatters ──────────────────────────────────────────────────────────────


def _fmt_delta(base: int, pr: int) -> str:
    delta = pr - base
    if delta == 0:
        return "0"
    return f"{'+' if delta > 0 else ''}{delta}"


def _fmt_seconds(s: float | None) -> str:
    if s is None:
        return "—"
    return f"{s:.1f}s"


def _fmt_exec_delta(base: float | None, pr: float | None) -> str:
    if base is None or pr is None or base == 0:
        return "—"
    delta = pr - base
    pct = (delta / base) * 100
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.1f}s ({sign}{pct:.1f}%)"


# ── Reconciliation helpers ──────────────────────────────────────────────────


def _db_from_qn(qn: str) -> str:
    """Extract the first path segment after the connection qualifiedName."""
    parts = qn.replace(CANONICAL_CONNECTION_QN + "/", "").split("/")
    return parts[0] if parts else ""


def _classify_attr(attr: str, qn: str) -> str:
    """Classify an attribute diff: known v3 improvement / live-DB variance / unexplained."""
    if attr in KNOWN_V3_IMPROVEMENTS:
        return "known v3 improvement"
    db = _db_from_qn(qn)
    if db in SYSTEM_DATABASES:
        return "live-DB variance (system DB)"
    if attr in LOOSE_COMPARE_FIELDS:
        return "live-DB variance (loose field)"
    return "unexplained"


def _cmp_values(v2, v3) -> bool:
    """Match _compare_values in test_parity.py semantics."""
    if v2 == v3:
        return True
    if v2 in (None, "") and v3 in (None, ""):
        return True
    return False


# ── Summary sections ────────────────────────────────────────────────────────


def _emit_count_table(
    lines: list[str],
    output_dir: Path,
    scenarios: list[str],
    title: str,
    timing_key_fmt: str,
    fallback: bool,
) -> None:
    """Render a per-scenario/entity record-count table.

    ``timing_key_fmt`` is either ``"reported"`` (use RESULT_COUNT_FIELDS) or
    a format string like ``"transformed_{entity}_rows"``. ``fallback=True``
    falls back to counting jsonl lines when the timing key is absent.
    """
    table_rows: list[str] = []
    for sc in scenarios:
        sc_dir = output_dir / sc
        base_timing = _load_timing(sc_dir / "api_golden" / "timing.json")
        pr_timing = _load_timing(sc_dir / "api_v3" / "timing.json")
        for entity in ENTITY_TYPES:
            key = (
                RESULT_COUNT_FIELDS[entity]
                if timing_key_fmt == "reported"
                else timing_key_fmt.format(entity=entity)
            )
            if key in base_timing or key in pr_timing:
                base_count = int(base_timing.get(key, 0) or 0)
                pr_count = int(pr_timing.get(key, 0) or 0)
            elif fallback:
                base_count = len(_load_jsonl(sc_dir / "golden" / f"{entity}.jsonl"))
                pr_count = len(_load_jsonl(sc_dir / "v3" / f"{entity}.jsonl"))
            else:
                base_count, pr_count = 0, 0
            if base_count == 0 and pr_count == 0:
                continue
            table_rows.append(
                f"| `{sc}` | {entity} | {base_count} | {pr_count} "
                f"| {_fmt_delta(base_count, pr_count)} |"
            )
    lines.append(f"### {title}")
    lines.append("")
    if table_rows:
        lines.append("| Scenario | Entity | Baseline | PR | Δ |")
        lines.append("|----------|--------|---------:|---:|--:|")
        lines.extend(table_rows)
    else:
        lines.append("_No data._")
    lines.append("")


def _emit_reconciled_deltas(
    lines: list[str], output_dir: Path, scenarios: list[str]
) -> None:
    """Collapse v3's table→view promotion into a single net-missing/net-extra row.

    v2 stores views as TABLE_TYPE=VIEW inside table.jsonl; v3 splits them into
    a dedicated view entity. The raw entity-diff section shows this as paired
    remove+add per view — which is expected, not a regression. This section
    reports the *real* delta: what's missing / extra once table+view are
    treated as one bucket.
    """
    lines.append("### Reconciled deltas (table + view merged)")
    lines.append("")
    lines.append("| Scenario | v2 table | v3 table+view | Missing | Extra | Status |")
    lines.append("|----------|---------:|--------------:|--------:|------:|:------:|")
    for sc in scenarios:
        sc_dir = output_dir / sc
        v2 = _qns(_load_jsonl(sc_dir / "golden" / "table.jsonl"))
        v3_t = _qns(_load_jsonl(sc_dir / "v3" / "table.jsonl"))
        v3_v = _qns(_load_jsonl(sc_dir / "v3" / "view.jsonl"))
        combined = v3_t | v3_v
        missing = v2 - combined
        extra = combined - v2
        status = "✅" if not missing and not extra else "⚠️"
        lines.append(
            f"| `{sc}` | {len(v2)} | {len(v3_t)}+{len(v3_v)}={len(combined)} "
            f"| {len(missing)} | {len(extra)} | {status} |"
        )
    lines.append("")


def _emit_attribute_drift(
    lines: list[str], output_dir: Path, scenarios: list[str]
) -> None:
    """Bucket per-attribute diffs across all shared QNs, classified by cause.

    For each qualifiedName present in both v2 and v3 (same entity type),
    diff every attribute value and count by attribute name. Cross-reference
    test_parity.py's classification so the reviewer can tell expected drift
    from unexplained regressions at a glance.
    """
    # attr_name -> classification -> count
    drift: dict[str, dict[str, int]] = {}
    # For a representative example per unexplained attribute
    unexplained_examples: dict[str, tuple[str, object, object]] = {}

    for sc in scenarios:
        sc_dir = output_dir / sc
        for entity in ENTITY_TYPES:
            v2_rec = _by_qn(_load_jsonl(sc_dir / "golden" / f"{entity}.jsonl"))
            v3_rec = _by_qn(_load_jsonl(sc_dir / "v3" / f"{entity}.jsonl"))
            shared = set(v2_rec) & set(v3_rec)
            for qn in shared:
                v2_a = v2_rec[qn].get("attributes", {})
                v3_a = v3_rec[qn].get("attributes", {})
                for key in set(v2_a) | set(v3_a):
                    if key in VOLATILE_FIELDS or key == "qualifiedName":
                        continue
                    if _cmp_values(v2_a.get(key), v3_a.get(key)):
                        continue
                    cls = _classify_attr(key, qn)
                    drift.setdefault(key, {}).setdefault(cls, 0)
                    drift[key][cls] += 1
                    if cls == "unexplained" and key not in unexplained_examples:
                        unexplained_examples[key] = (
                            qn,
                            v2_a.get(key),
                            v3_a.get(key),
                        )

    lines.append("### Attribute drift (shared qualifiedNames only)")
    lines.append("")
    if not drift:
        lines.append("_No attribute differences on shared assets._")
        lines.append("")
        return

    # Sort: unexplained first (highest unexplained count), then by total count
    def _sort_key(item):
        attr, classes = item
        unexplained = classes.get("unexplained", 0)
        total = sum(classes.values())
        return (-unexplained, -total)

    sorted_drift = sorted(drift.items(), key=_sort_key)

    lines.append(
        "| Attribute | Unexplained | Known v3 improvement | Live-DB variance | Total |"
    )
    lines.append(
        "|-----------|------------:|---------------------:|-----------------:|------:|"
    )
    truncated = max(0, len(sorted_drift) - MAX_ATTR_ROWS)
    for attr, classes in sorted_drift[:MAX_ATTR_ROWS]:
        unexplained = classes.get("unexplained", 0)
        known = classes.get("known v3 improvement", 0)
        variance = classes.get("live-DB variance (system DB)", 0) + classes.get(
            "live-DB variance (loose field)", 0
        )
        total = unexplained + known + variance
        flag = "⚠️ " if unexplained else ""
        lines.append(
            f"| {flag}`{attr}` | {unexplained} | {known} | {variance} | {total} |"
        )
    if truncated:
        lines.append(f"| _…{truncated} more attributes_ | | | | |")
    lines.append("")

    if unexplained_examples:
        lines.append(
            "<details><summary>Unexplained drift — first example per attribute</summary>"
        )
        lines.append("")
        for attr, (qn, v2v, v3v) in list(unexplained_examples.items())[:MAX_ATTR_ROWS]:
            lines.append(f"- `{attr}` on `{qn}`: `{v2v!r}` → `{v3v!r}`")
        lines.append("")
        lines.append("</details>")
        lines.append("")


def _emit_entity_diffs(
    lines: list[str], output_dir: Path, scenarios: list[str]
) -> None:
    """Raw per-scenario/entity added/removed qualifiedNames."""
    lines.append("### Entity diffs (raw added/removed)")
    lines.append("")
    any_diff = False
    diff_lines: list[str] = []
    for sc in scenarios:
        sc_dir = output_dir / sc
        for entity in ENTITY_TYPES:
            base_qns = _qns(_load_jsonl(sc_dir / "golden" / f"{entity}.jsonl"))
            pr_qns = _qns(_load_jsonl(sc_dir / "v3" / f"{entity}.jsonl"))
            added = sorted(pr_qns - base_qns)
            removed = sorted(base_qns - pr_qns)
            if added or removed:
                any_diff = True
                diff_lines.append(f"\n**`{sc}` → `{entity}`**")
                if added:
                    shown = added[:MAX_ITEMS]
                    diff_lines.append(f"- Added ({len(added)}): ")
                    diff_lines += [f"  - `{q}`" for q in shown]
                    if len(added) > MAX_ITEMS:
                        diff_lines.append(f"  - _…and {len(added) - MAX_ITEMS} more_")
                if removed:
                    shown = removed[:MAX_ITEMS]
                    diff_lines.append(f"- Removed ({len(removed)}):")
                    diff_lines += [f"  - `{q}`" for q in shown]
                    if len(removed) > MAX_ITEMS:
                        diff_lines.append(f"  - _…and {len(removed) - MAX_ITEMS} more_")
    if any_diff:
        lines.append(
            "<details><summary>Expand — most of these are expected (v2 table→v3 view promotion)</summary>"
        )
        lines.append("")
        lines += diff_lines
        lines.append("")
        lines.append("</details>")
    else:
        lines.append("_No added or removed entities — qualifiedNames match._")
    lines.append("")


def _emit_timing(lines: list[str], output_dir: Path, scenarios: list[str]) -> None:
    """Just exec_duration — wall-clock is dominated by the 10s status poll interval."""
    lines.append("### Execution duration (server-side)")
    lines.append("")
    lines.append("| Scenario | Baseline | PR | Δ |")
    lines.append("|----------|---------:|---:|:--|")
    any_timing = False
    for sc in scenarios:
        sc_dir = output_dir / sc
        base_t = _load_timing(sc_dir / "api_golden" / "timing.json")
        pr_t = _load_timing(sc_dir / "api_v3" / "timing.json")
        if not base_t and not pr_t:
            continue
        any_timing = True
        base_s = base_t.get("execution_duration_seconds")
        pr_s = pr_t.get("execution_duration_seconds")
        lines.append(
            f"| `{sc}` | {_fmt_seconds(base_s)} | {_fmt_seconds(pr_s)} "
            f"| {_fmt_exec_delta(base_s, pr_s)} |"
        )
    if not any_timing:
        lines = lines[:-2]
        lines.append("_No timing data recorded._")
    lines.append("")


def _emit_pytest_results(lines: list[str], junit_xml: Path) -> None:
    """Parse pytest JUnit XML and report pass/fail by test class."""
    lines.append("### Pytest results")
    lines.append("")
    if not junit_xml.is_file():
        lines.append("_No pytest results at `{}`._".format(junit_xml))
        lines.append("")
        return
    try:
        root = ET.parse(junit_xml).getroot()
    except ET.ParseError as exc:
        lines.append(f"_Failed to parse `{junit_xml}`: {exc}._")
        lines.append("")
        return

    # per-class counts
    per_class: dict[str, dict[str, int]] = {}
    for tc in root.iter("testcase"):
        cls = tc.get("classname", "") or "<unknown>"
        # Trim module prefix (keep only the class)
        cls = cls.rsplit(".", 1)[-1]
        bucket = per_class.setdefault(
            cls, {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}
        )
        if tc.find("failure") is not None:
            bucket["failed"] += 1
        elif tc.find("error") is not None:
            bucket["errored"] += 1
        elif tc.find("skipped") is not None:
            bucket["skipped"] += 1
        else:
            bucket["passed"] += 1

    if not per_class:
        lines.append("_No testcases recorded._")
        lines.append("")
        return

    lines.append("| Test class | Passed | Failed | Errored | Skipped |")
    lines.append("|------------|-------:|-------:|--------:|--------:|")
    for cls, b in sorted(per_class.items()):
        status = "✅" if b["failed"] == 0 and b["errored"] == 0 else "❌"
        lines.append(
            f"| {status} `{cls}` | {b['passed']} | {b['failed']} "
            f"| {b['errored']} | {b['skipped']} |"
        )
    lines.append("")


# ── Entry point ─────────────────────────────────────────────────────────────


def summarize(output_dir: Path, junit_xml: Path | None = None) -> str:
    if not output_dir.is_dir():
        return f"## Parity Report\n\n_No output at `{output_dir}`._\n"

    scenarios = sorted(
        d.name
        for d in output_dir.iterdir()
        if d.is_dir() and ((d / "golden").is_dir() or (d / "v3").is_dir())
    )
    if not scenarios:
        return "## Parity Report\n\n_No scenarios with comparable output._\n"

    lines: list[str] = [
        "## Parity Report — main vs PR",
        "",
        f"**Scenarios covered:** {', '.join(f'`{s}`' for s in scenarios)}",
        "",
    ]

    _emit_count_table(
        lines,
        output_dir,
        scenarios,
        "Record counts (reported by /result)",
        "reported",
        fallback=True,
    )
    _emit_count_table(
        lines,
        output_dir,
        scenarios,
        "Record counts (transformed)",
        "transformed_{entity}_rows",
        fallback=False,
    )
    _emit_reconciled_deltas(lines, output_dir, scenarios)
    _emit_attribute_drift(lines, output_dir, scenarios)
    _emit_entity_diffs(lines, output_dir, scenarios)
    _emit_timing(lines, output_dir, scenarios)
    if junit_xml is not None:
        _emit_pytest_results(lines, junit_xml)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="tests/parity/output",
        help="Path to tests/parity/output (default: %(default)s)",
    )
    parser.add_argument(
        "--junit-xml",
        default="results/parity.xml",
        help="Path to pytest JUnit XML (default: %(default)s)",
    )
    args = parser.parse_args()
    junit = Path(args.junit_xml) if args.junit_xml else None
    print(summarize(Path(args.output_dir), junit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
