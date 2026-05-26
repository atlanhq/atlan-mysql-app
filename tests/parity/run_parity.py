#!/usr/bin/env python3
"""Run parity: generate v2 golden + v3 output per scenario, then compare.

Discovers e2e scenarios, runs workflows on both v2 and v3, saves normalized
output per scenario, then runs pytest to compare.

Usage:
  # Full run (both v2 golden + v3 output + comparison):
  uv run python tests/parity/run_parity.py

  # Only generate v2 golden:
  uv run python tests/parity/run_parity.py --v2-only

  # Only generate v3 output (golden must already exist):
  uv run python tests/parity/run_parity.py --v3-only

  # Single scenario:
  uv run python tests/parity/run_parity.py --scenario empty_filters

  # Custom hosts:
  uv run python tests/parity/run_parity.py --v2-host http://localhost:3000 --v3-host http://localhost:8000

  # Skip pytest, just generate outputs:
  uv run python tests/parity/run_parity.py --no-test
"""

from __future__ import annotations

import argparse
import glob as _glob
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_recorder import (
    normalize_api_response,
    record_auth,
    record_metadata,
    record_preflight,
    record_result,
    save_api_responses,
)
from dotenv import load_dotenv

try:
    from .parity_entities import ENTITY_TYPES, RESULT_COUNT_FIELDS
except ImportError:
    from parity_entities import ENTITY_TYPES, RESULT_COUNT_FIELDS
PARITY_DIR = Path(__file__).parent
OUTPUT_DIR = PARITY_DIR / "output"
INTEGRATION_DIR = PARITY_DIR.parent / "integration"
CANONICAL_CONNECTION_QN = "default/mysql/__PARITY__"
VOLATILE_KEYS = {"lastSyncWorkflowName", "lastSyncRun", "lastSyncRunAt", "tenantId"}

# Maps integration-test api types to (recorder_fn, endpoint_filename).
# endpoint_filename must match the ENDPOINTS list in test_contract_parity.py
# ("auth", "check", "metadata", "start", "status", "result").
_API_RECORDERS: dict[str, tuple] = {
    "auth": (record_auth, "auth"),
    "preflight": (record_preflight, "check"),
    "metadata": (record_metadata, "metadata"),
}


# ── Env & Config ────────────────────────────────────────────────────────────


def _load_env() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _load_integration_cls():
    """Import TestMySQLIntegration without triggering pytest collection."""
    # TODO(mysql-parity-port): tests/integration/test_mysql_integration.py
    # does not yet exist in this repo. Parity discovery will fail until
    # the integration suite is ported.
    spec = importlib.util.spec_from_file_location(
        "test_mysql_integration",
        INTEGRATION_DIR / "test_mysql_integration.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TestMySQLIntegration


def _build_default_creds(cls) -> dict:
    """Build baseline credentials from E2E_MYSQL_* env vars + class defaults."""
    port_env = os.environ.get("E2E_MYSQL_PORT", "3306")
    creds: dict = {
        "authType": "basic",
        "type": "all",
        "username": os.environ.get("E2E_MYSQL_USERNAME", ""),
        "password": os.environ.get("E2E_MYSQL_PASSWORD", ""),
        "host": os.environ.get("E2E_MYSQL_HOST", ""),
        "port": int(port_env) if port_env.isdigit() else port_env,
        "extra": {
            # TODO(mysql-parity-port): confirm the canonical sample db name
            # once tests/integration/test_mysql_integration.py exists.
            "database": os.environ.get("E2E_MYSQL_DATABASE", "ecommerce"),
        },
    }
    creds.update(cls.default_credentials)
    return creds


def _build_scenario_args(cls, scenario) -> dict:
    """Build workflow_args from a Scenario, applying class defaults + hooks."""
    creds = (
        dict(scenario.credentials)
        if scenario.credentials is not None
        else _build_default_creds(cls)
    )
    # Apply the connector-specific credential transform (e.g. move database → extra)
    instance = cls.__new__(cls)
    if hasattr(instance, "build_credentials"):
        try:
            creds = instance.build_credentials(creds)
        except Exception as exc:
            print(f"    Warning: build_credentials raised {exc}")
    metadata = {**cls.default_metadata, **(scenario.metadata or {})}
    connection = {**cls.default_connection, **(scenario.connection or {})}
    return {"connection": connection, "credentials": creds, "metadata": metadata}


def _load_scenarios(single: str | None = None) -> list[tuple[str, dict, str]]:
    """Return (name, workflow_args, api_type) for every non-skipped scenario.

    Reads directly from ``TestMySQLIntegration.scenarios`` — no config.yaml needed.
    """
    cls = _load_integration_cls()
    out: list[tuple[str, dict, str]] = []
    for s in cls.scenarios:
        if s.skip:
            print(f"  [skip] {s.name}: {s.skip_reason or 'skip=True'}")
            continue
        if single and s.name != single:
            continue
        out.append((s.name, _build_scenario_args(cls, s), s.api))
    return out


# ── Normalization ───────────────────────────────────────────────────────────


def _normalize_value(v: object, connection_qn: str) -> object:
    if isinstance(v, str) and connection_qn in v:
        return v.replace(connection_qn, CANONICAL_CONNECTION_QN)
    if isinstance(v, dict):
        return {dk: _normalize_value(dv, connection_qn) for dk, dv in v.items()}
    if isinstance(v, list):
        return [_normalize_value(item, connection_qn) for item in v]
    return v


def _normalize_record(record: dict, connection_qn: str) -> dict:
    attrs = record.get("attributes", {})
    cleaned = {}
    for k, v in attrs.items():
        if k in VOLATILE_KEYS:
            continue
        cleaned[k] = _normalize_value(v, connection_qn)
    return {
        "typeName": record.get("typeName", ""),
        "status": record.get("status", ""),
        "attributes": cleaned,
    }


def _sort_key(r: dict) -> str:
    return r.get("attributes", {}).get("qualifiedName", "")


def _eval_concat_expr(expr: str, row: dict) -> str | None:
    """Evaluate concat(col1, '/', col2, ...) from a YAML template source_query."""
    if not (expr.startswith("concat(") and expr.endswith(")")):
        return None
    inner = expr[7:-1]
    parts = [p.strip() for p in inner.split(",")]
    result = []
    for part in parts:
        if part.startswith("'") and part.endswith("'"):
            result.append(part[1:-1])
        else:
            val = row.get(part)
            if val is None:
                return None
            result.append(str(val))
    return "".join(result)


def _read_raw_parquets_as_entities(output_base: str, entity: str) -> list[dict]:
    """Read v2 SDK raw parquet output from raw/<entity>/ using YAML transformer templates.

    v2 SDK (2.8.1) writes SQL query results as raw parquets to raw/<entity>/
    with no transformed/ directory. Apply the matching YAML template to produce
    minimal Atlan entity dicts with qualifiedName, typeName, status, and
    scalar attributes — enough for all parity test assertions.

    Special case: v2 stores views inside raw/table/ (TABLE_TYPE=VIEW).  When
    entity="view" we read from raw/table/ with table.yaml and keep only the
    View-typed rows so the golden count matches v3's view extraction.
    """
    # v2 stores views inside raw/table/ — redirect lookup accordingly
    raw_entity = "table" if entity == "view" else entity
    raw_entity_dir = os.path.join(output_base, "raw", raw_entity)
    if not os.path.isdir(raw_entity_dir):
        return []

    pq_files = sorted(
        _glob.glob(os.path.join(raw_entity_dir, "**/*.parquet"), recursive=True)
    ) or sorted(_glob.glob(os.path.join(raw_entity_dir, "*.parquet")))
    if not pq_files:
        return []

    try:
        import pandas as pd
        import yaml as _yaml
    except ImportError:
        return []

    # TODO(mysql-parity-port): mysql's v2 SDK shape (sql_query_templates dir)
    # is unknown — this fallback returns [] until the v2 baseline is
    # wired up. v3-only runs do not need this code path.
    template_file = (
        Path(__file__).resolve().parent.parent.parent
        / "app"
        / "transformers"
        / "query"
        / "sql_query_templates"
        / f"{raw_entity}.yaml"
    )
    if not template_file.exists():
        return []

    with open(template_file) as f:
        template = _yaml.safe_load(f)

    cols = template.get("columns", {})
    attrs_defs = cols.get("attributes", {})
    typename_sq = str(cols.get("typeName", {}).get("source_query", "")).strip()
    status_sq = str(cols.get("status", {}).get("source_query", "")).strip()
    default_status = (
        status_sq[1:-1]
        if status_sq.startswith("'") and status_sq.endswith("'")
        else "ACTIVE"
    )

    records: list[dict] = []
    for pq_file in pq_files:
        try:
            df = pd.read_parquet(pq_file)
        except Exception:
            continue
        for _, row in df.iterrows():
            # Coerce every cell to str; treat NaN (v != v) as None
            row_dict: dict = {}
            for k, v in row.items():
                if v is None or v != v:  # None or NaN
                    row_dict[k] = None
                else:
                    row_dict[k] = str(v)

            # Resolve typeName — simple literal or TABLE_TYPE CASE fallback
            if typename_sq.startswith("'") and typename_sq.endswith("'"):
                type_name = typename_sq[1:-1]
            else:
                tt = str(row_dict.get("TABLE_TYPE") or "TABLE")
                type_name = "View" if tt == "VIEW" else "Table"

            attrs: dict = {}
            for attr_name, attr_def in attrs_defs.items():
                if not isinstance(attr_def, dict):
                    continue
                sq = str(attr_def.get("source_query", "")).strip()
                if not sq:
                    continue
                if sq.startswith("'") and sq.endswith("'"):
                    val: object = sq[1:-1]
                elif sq.startswith("concat(") and sq.endswith(")"):
                    val = _eval_concat_expr(sq, row_dict)
                else:
                    # Simple column ref or complex CASE — use first source_column
                    src_cols = attr_def.get("source_columns", [])
                    col = src_cols[0] if src_cols else sq.split()[0]
                    val = row_dict.get(col)
                if val is not None:
                    attrs[attr_name] = val

            if not attrs.get("qualifiedName"):
                continue
            # When reading views from raw/table/, keep only View-typed rows
            if entity == "view" and type_name != "View":
                continue
            records.append(
                {"typeName": type_name, "status": default_status, "attributes": attrs}
            )

    return records


# ── I/O ─────────────────────────────────────────────────────────────────────


def _read_transformed(output_base: str) -> dict[str, list[dict]]:
    """Read transformed output, searching multiple possible output paths.

    The v3 app may write raw parquet to ./local/tmp/ and transformed JSON
    to ./local/dapr/objectstore/ (via Dapr). This function checks all known
    output bases for the same workflow subpath (e.g. 'local/transformed/').
    """
    # Extract the workflow-relative path (e.g. "local" from ".../workflows/local")
    # so we can check the same relative path under all output bases
    abs_output = os.path.abspath(output_base)
    workflow_subpath = ""
    for base in _OUTPUT_ROOTS:
        abs_base = os.path.abspath(base)
        if abs_output.startswith(abs_base):
            workflow_subpath = abs_output[len(abs_base) :].strip("/")
            break

    # Collect all dirs to search for transformed output
    search_dirs = [output_base]
    if workflow_subpath:
        for base in _OUTPUT_ROOTS:
            candidate = os.path.join(base, workflow_subpath)
            abs_candidate = os.path.abspath(candidate)
            if abs_candidate != abs_output and os.path.isdir(candidate):
                search_dirs.append(candidate)

    results: dict[str, list[dict]] = {}

    for entity in ENTITY_TYPES:
        records: list[dict] = []

        for search_dir in search_dirs:
            transformed_dir = os.path.join(search_dir, "transformed")
            entity_dir = os.path.join(transformed_dir, entity)

            # JSON files
            if os.path.isdir(entity_dir):
                for json_file in sorted(
                    _glob.glob(os.path.join(entity_dir, "**/*.json"), recursive=True)
                ):
                    if "statistics" in json_file:
                        continue
                    with open(json_file) as f:
                        for line in f:
                            if line.strip():
                                records.append(json.loads(line))

            if records:
                break  # Found JSON in this search dir, don't check others

            # Parquet fallback
            if not records:
                try:
                    import pandas as pd

                    search = (
                        entity_dir if os.path.isdir(entity_dir) else transformed_dir
                    )
                    for pq_file in sorted(
                        _glob.glob(os.path.join(search, f"{entity}*.parquet"))
                    ):
                        df = pd.read_parquet(pq_file)
                        records.extend(df.to_dict(orient="records"))
                except ImportError:
                    pass

            if records:
                break

        # v2 SDK fallback: no transformed/ dir — reads raw/<entity>/ parquets
        # using the YAML transformer templates to reconstruct Atlan entity shape.
        if not records:
            for sd in search_dirs:
                raw_recs = _read_raw_parquets_as_entities(sd, entity)
                if raw_recs:
                    records.extend(raw_recs)
                    break

        results[entity] = records
    return results


def _save_normalized(
    out_dir: Path, data: dict[str, list[dict]], connection_qn: str
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for entity, records in data.items():
        normalized = sorted(
            [_normalize_record(r, connection_qn) for r in records],
            key=_sort_key,
        )
        out_file = out_dir / f"{entity}.jsonl"
        with open(out_file, "w") as f:
            for rec in normalized:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        print(f"    {entity}: {len(normalized)} records")


def _clear_previous_outputs(
    scenarios: list[tuple[str, dict, str]], run_v2: bool, run_v3: bool
) -> None:
    """Clear only the output slices that this invocation is about to regenerate."""
    for name, _, _ in scenarios:
        scenario_dir = OUTPUT_DIR / name
        if run_v2:
            shutil.rmtree(scenario_dir / "golden", ignore_errors=True)
            shutil.rmtree(scenario_dir / "api_golden", ignore_errors=True)
        if run_v3:
            shutil.rmtree(scenario_dir / "v3", ignore_errors=True)
            shutil.rmtree(scenario_dir / "api_v3", ignore_errors=True)

        if scenario_dir.exists() and not any(scenario_dir.iterdir()):
            scenario_dir.rmdir()


# ── Workflow Runner ─────────────────────────────────────────────────────────


# Root dirs under which apps write workflow artifacts.
# We glob for any app name (mysql, default, …) so the search is not coupled
# to ATLAN_APPLICATION_NAME.
#
# In CI, Dapr starts from $GITHUB_WORKSPACE (the PR checkout), so its
# localstore rootPath "./local/dapr/objectstore" resolves under
# $GITHUB_WORKSPACE — not under $BASELINE_TREE where the baseline
# orchestrator runs. Prepend the absolute path so _read_transformed and
# _find_workflow_output can locate v2's transform_data JSON output.
_OUTPUT_ROOTS_BASE = [
    "./local/dapr/objectstore/artifacts/apps",
    "./local/tmp/artifacts/apps",
]
_gw = os.environ.get("GITHUB_WORKSPACE", "")
_OUTPUT_ROOTS: list[str] = (
    [os.path.join(_gw, "local/dapr/objectstore/artifacts/apps")] + _OUTPUT_ROOTS_BASE
    if _gw
    else _OUTPUT_ROOTS_BASE
)


def _workflow_bases() -> list[str]:
    """Return every <root>/<app_name>/workflows dir that currently exists."""
    bases: list[str] = []
    for root in _OUTPUT_ROOTS:
        for app_dir in _glob.glob(os.path.join(root, "*")):
            wf_dir = os.path.join(app_dir, "workflows")
            if os.path.isdir(wf_dir):
                bases.append(wf_dir)
    return bases


def _find_workflow_output(wf_id: str, run_id: str) -> str:
    """Find the output dir for a specific workflow run.

    Searches all <root>/<app>/workflows trees so the result is independent
    of the ATLAN_APPLICATION_NAME value used at runtime.
    Fails hard if the exact wf_id/run_id directory is not found — no
    fallback to "most recent" to avoid silently reading stale artifacts.
    """
    for base in _workflow_bases():
        exact = Path(base) / wf_id / run_id
        if exact.is_dir() and (
            (exact / "raw").is_dir() or (exact / "transformed").is_dir()
        ):
            return str(exact)

    raise FileNotFoundError(
        f"No output found for workflow {wf_id}/{run_id}. "
        "Searched: " + ", ".join(_workflow_bases())
    )


@dataclass
class WorkflowRunResult:
    output_path: str
    start_response: dict = field(default_factory=dict)
    final_status_response: dict = field(default_factory=dict)
    wall_clock_seconds: float = 0.0
    workflow_id: str = ""
    run_id: str = ""


def _run_workflow(
    api_base: str, workflow_args: dict, timeout: int = 300
) -> WorkflowRunResult:
    """POST /start, poll /status, return WorkflowRunResult with output path + metadata."""
    # Clear stale output under every known app/workflows tree so we only
    # read fresh data from this run.
    for base in _workflow_bases():
        if os.path.isdir(base):
            shutil.rmtree(base, ignore_errors=True)
            print(f"    Cleared: {base}")

    t0 = time.monotonic()

    resp = requests.post(f"{api_base}/start", json=workflow_args, timeout=30)
    assert resp.status_code == 200, f"/start failed: {resp.text}"
    data = resp.json()
    assert data["success"] is True, f"/start not successful: {data}"

    wf_id = data["data"]["workflow_id"]
    run_id = data["data"]["run_id"]
    start_response = data
    print(f"    workflow_id={wf_id}")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            sr = requests.get(f"{api_base}/status/{wf_id}/{run_id}", timeout=60)
        except requests.exceptions.ReadTimeout:
            time.sleep(5)
            continue
        if sr.status_code == 200:
            status_data = sr.json()
            status = status_data.get("data", {}).get("status", "").upper()
            if status in ("COMPLETED", "SUCCEEDED"):
                wall_clock = time.monotonic() - t0
                print(f"    Completed: {status} ({wall_clock:.1f}s)")
                output = _find_workflow_output(wf_id, run_id)
                print(f"    Output: {output}")
                return WorkflowRunResult(
                    output_path=output,
                    start_response=start_response,
                    final_status_response=status_data,
                    wall_clock_seconds=wall_clock,
                    workflow_id=wf_id,
                    run_id=run_id,
                )
            if status in ("FAILED", "TERMINATED", "CANCELLED", "TIMED_OUT"):
                raise RuntimeError(f"Workflow {wf_id} failed: {status}")
        time.sleep(10)

    raise TimeoutError(f"Workflow did not complete in {timeout}s")


def _record_and_save_api(
    api_base: str,
    workflow_args: dict,
    result: WorkflowRunResult,
    out_dir: Path,
    version: str = "v3",
) -> None:
    """Call handler endpoints + result, normalize, and save all API responses."""
    responses: dict[str, dict] = {}

    # Handler endpoints
    print("    Recording API responses...")
    responses["auth"] = record_auth(api_base, workflow_args, version=version)
    responses["check"] = record_preflight(api_base, workflow_args, version=version)
    responses["metadata"] = record_metadata(api_base, workflow_args, version=version)

    # Workflow lifecycle responses (already captured)
    responses["start"] = {"status_code": 200, "body": result.start_response}
    responses["status"] = {"status_code": 200, "body": result.final_status_response}

    # Result endpoint
    if result.workflow_id:
        responses["result"] = record_result(api_base, result.workflow_id)

    # Timing data — extract counts from result endpoint or transformed output
    exec_dur = result.final_status_response.get("data", {}).get(
        "execution_duration_seconds", 0
    )
    result_data = responses.get("result", {}).get("body", {}).get("data", {})
    # v3 nests counts under data.result, v2 may put them under data directly
    counts = result_data.get("result", result_data)

    transformed = _read_transformed(result.output_path)
    transformed_counts = {
        field: len(transformed.get(entity, []))
        for entity, field in RESULT_COUNT_FIELDS.items()
    }
    counts = {
        field: counts.get(field, transformed_counts[field]) or transformed_counts[field]
        for field in RESULT_COUNT_FIELDS.values()
    }

    responses["timing"] = {
        "wall_clock_seconds": round(result.wall_clock_seconds, 2),
        "execution_duration_seconds": exec_dur,
        **counts,
        **{
            f"transformed_{entity}_rows": transformed_counts[field]
            for entity, field in RESULT_COUNT_FIELDS.items()
        },
    }

    # Normalize API responses but keep timing as-is (it's our own metrics)
    normalized = {
        k: normalize_api_response(v) if k != "timing" else v
        for k, v in responses.items()
    }
    save_api_responses(out_dir, normalized)


# Cache: credentials fingerprint -> credential_guid.
# Keyed by content so scenarios with different credentials each get their own guid.
_v3_credential_cache: dict[str, str] = {}


def _provision_v3_credentials(api_base: str, workflow_args: dict) -> str:
    """POST credentials to /dev/local-vault; cache by content and return the credential_guid.

    v3 strips inline credentials from Temporal payloads. Activities resolve
    them via DaprCredentialVault using credential_guid, so we must provision
    before each scenario that uses distinct credentials.
    """
    creds = workflow_args.get("credentials", {})
    creds_key = hashlib.md5(
        json.dumps(creds, sort_keys=True).encode(), usedforsecurity=False
    ).hexdigest()
    if creds_key in _v3_credential_cache:
        return _v3_credential_cache[creds_key]

    resp = requests.post(f"{api_base}/dev/local-vault", json=creds, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    guid = body.get("data", {}).get("credential_guid") or body.get(
        "credential_guid", ""
    )
    if not guid:
        raise RuntimeError(f"No credential_guid returned from local-vault: {body}")
    _v3_credential_cache[creds_key] = guid
    print(f"    Provisioned v3 credentials: guid={guid}")
    return guid


def _check_host(host: str, label: str) -> None:
    try:
        requests.get(f"{host}/health", timeout=10)
    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
        # Fallback: try root (v2 may not have /health)
        try:
            requests.get(host, timeout=10)
        except requests.exceptions.ConnectionError:
            print(f"ERROR: {label} not reachable at {host}")
            sys.exit(1)


# ── Main ────────────────────────────────────────────────────────────────────


def _run_api_scenario(
    name: str,
    api_type: str,
    workflow_args: dict,
    run_v2: bool,
    run_v3: bool,
    v2_host: str,
    v3_host: str,
    no_api_record: bool,
) -> None:
    """Record API response for a non-workflow scenario on v2 and/or v3."""
    entry = _API_RECORDERS.get(api_type)
    if entry is None:
        print(f"  [{name}] No recorder for api_type={api_type!r}, skipping")
        return
    recorder, endpoint_key = entry

    if run_v2:
        api_golden_dir = OUTPUT_DIR / name / "api_golden"
        if not no_api_record:
            print(f"  [v2] Recording {api_type} ({endpoint_key}) on {v2_host}...")
            resp = recorder(f"{v2_host}/workflows/v1", workflow_args, version="v2")
            save_api_responses(
                api_golden_dir, {endpoint_key: normalize_api_response(resp)}
            )

    if run_v3:
        api_v3_dir = OUTPUT_DIR / name / "api_v3"
        if not no_api_record:
            print(f"  [v3] Recording {api_type} ({endpoint_key}) on {v3_host}...")
            resp = recorder(f"{v3_host}/workflows/v1", workflow_args, version="v3")
            save_api_responses(api_v3_dir, {endpoint_key: normalize_api_response(resp)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v2-vs-v3 parity tests")
    parser.add_argument("--v2-host", default="http://localhost:3000")
    parser.add_argument("--v3-host", default="http://localhost:8000")
    parser.add_argument(
        "--scenario", default=None, help="Single scenario name (default: all)"
    )
    parser.add_argument(
        "--v2-only", action="store_true", help="Only generate v2 golden"
    )
    parser.add_argument(
        "--v3-only", action="store_true", help="Only generate v3 output"
    )
    parser.add_argument("--no-test", action="store_true", help="Skip pytest comparison")
    parser.add_argument(
        "--no-api-record",
        action="store_true",
        help="Skip API contract/timing recording",
    )
    args = parser.parse_args()

    _load_env()
    scenarios = _load_scenarios(args.scenario)

    if not scenarios:
        print("No scenarios found in tests/integration/test_mysql_integration.py")
        sys.exit(1)

    run_v2 = not args.v3_only
    run_v3 = not args.v2_only
    failures: list[str] = []

    if run_v2:
        _check_host(args.v2_host, "v2")
    if run_v3:
        _check_host(args.v3_host, "v3")

    _clear_previous_outputs(scenarios, run_v2, run_v3)

    for name, workflow_args, api_type in scenarios:
        connection_qn = workflow_args["connection"]["connection_qualified_name"]

        print(f"\n{'=' * 60}")
        print(f"  Scenario: {name} [{api_type}]")
        print(f"{'=' * 60}")

        # ── Non-workflow scenarios: just record the API response ─────
        if api_type != "workflow":
            try:
                _run_api_scenario(
                    name,
                    api_type,
                    workflow_args,
                    run_v2,
                    run_v3,
                    args.v2_host,
                    args.v3_host,
                    args.no_api_record,
                )
            except Exception as e:
                failures.append(f"{name}: API scenario failed: {e}")
                print(f"  FAILED: {failures[-1]}")
            continue

        # ── Workflow scenarios: run full extraction + compare output ──

        # v2 golden
        if run_v2:
            golden_dir = OUTPUT_DIR / name / "golden"
            api_golden_dir = OUTPUT_DIR / name / "api_golden"
            print(f"  [v2] Running workflow on {args.v2_host}...")
            try:
                v2_api_base = f"{args.v2_host}/workflows/v1"
                v2_result = _run_workflow(v2_api_base, workflow_args)
                v2_data = _read_transformed(v2_result.output_path)
                _save_normalized(golden_dir, v2_data, connection_qn)
                if not args.no_api_record:
                    _record_and_save_api(
                        v2_api_base,
                        workflow_args,
                        v2_result,
                        api_golden_dir,
                        version="v2",
                    )
            except Exception as e:
                failures.append(f"{name}: v2 collection failed: {e}")
                print(f"  [v2] FAILED: {e}")
                continue

        # v3 output
        if run_v3:
            v3_dir = OUTPUT_DIR / name / "v3"
            api_v3_dir = OUTPUT_DIR / name / "api_v3"
            print(f"  [v3] Running workflow on {args.v3_host}...")
            try:
                v3_api_base = f"{args.v3_host}/workflows/v1"
                guid = _provision_v3_credentials(v3_api_base, workflow_args)
                # Flatten metadata filters to top-level so ExtractionInput
                # receives them regardless of which payload path SDK uses.
                _meta = workflow_args.get("metadata", {})
                v3_workflow_args = {
                    **workflow_args,
                    "credential_guid": guid,
                    "include_filter": _meta.get("include-filter", ""),
                    "exclude_filter": _meta.get("exclude-filter", ""),
                    "temp_table_regex": _meta.get("temp-table-regex", ""),
                }
                v3_result = _run_workflow(v3_api_base, v3_workflow_args)
                v3_data = _read_transformed(v3_result.output_path)
                _save_normalized(v3_dir, v3_data, connection_qn)
                if not args.no_api_record:
                    _record_and_save_api(
                        v3_api_base,
                        v3_workflow_args,
                        v3_result,
                        api_v3_dir,
                        version="v3",
                    )
            except Exception as e:
                failures.append(f"{name}: v3 collection failed: {e}")
                print(f"  [v3] FAILED: {e}")
                continue

    if failures:
        print(f"\n{'=' * 60}")
        print("  Parity collection failures")
        print(f"{'=' * 60}")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)

    # ── Run comparison ──────────────────────────────────────────────
    if not args.no_test and run_v3:
        print(f"\n{'=' * 60}")
        print("  Running parity comparison...")
        print(f"{'=' * 60}\n")
        repo_root = PARITY_DIR.parent.parent
        results_dir = repo_root / "results"
        results_dir.mkdir(exist_ok=True)
        junit_xml = results_dir / "parity.xml"
        parity_txt = results_dir / "parity.txt"

        with open(parity_txt, "w") as log_fh:
            proc = subprocess.run(
                [
                    "uv",
                    "run",
                    "pytest",
                    "tests/parity/",
                    "-v",
                    "--timeout=60",
                    "--tb=short",
                    f"--junit-xml={junit_xml}",
                ],
                cwd=str(repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            log_fh.write(proc.stdout)

        # Echo to terminal so the operator sees live output
        print(proc.stdout)

        # Write human-readable summary
        try:
            try:
                from .summarize import summarize
            except ImportError:
                from summarize import summarize
            summary_md = summarize(OUTPUT_DIR)
            summary_file = results_dir / "parity_summary.md"
            summary_file.write_text(summary_md)
            print(f"\nSummary written to {summary_file}")
            print("\n" + summary_md[:3000])  # preview first 3k chars
        except Exception as exc:
            print(f"\nWarning: summary generation failed: {exc}")

        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
