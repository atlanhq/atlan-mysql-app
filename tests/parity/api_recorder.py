"""Record and normalize API responses from v2/v3 connector endpoints.

Used by run_parity.py to capture HTTP responses for contract + performance
parity testing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

# Dynamic fields replaced with placeholders during normalization
_DYNAMIC_PATTERNS: dict[str, str] = {
    "workflow_id": "__WORKFLOW_ID__",
    "run_id": "__RUN_ID__",
    "correlation_id": "__CORRELATION_ID__",
}

# Fields whose *values* are replaced but keys are kept
_TIMESTAMP_KEYS = {"lastSyncRunAt", "expires_at", "started_at", "completed_at"}
_DURATION_KEYS = {
    "execution_duration_seconds",
    "duration_ms",
    "total_duration_ms",
    "wall_clock_seconds",
}


# ── API Callers ────────────────────────────────────────────────────────────


def _creds_to_array(creds: dict) -> list[dict[str, str]]:
    """Convert nested credential dict to [{key, value}] array format for v3 handlers."""
    pairs: list[dict[str, str]] = []
    for k, v in creds.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                pairs.append({"key": f"{k}.{sk}", "value": str(sv)})
        else:
            pairs.append({"key": k, "value": str(v)})
    return pairs


def _build_auth_body(workflow_args: dict, version: str) -> dict:
    """Build request body for handler endpoints, adapting to v2 vs v3 format."""
    creds = workflow_args.get("credentials", {})
    if version == "v2":
        # v2 expects flat credential dict at top level
        return creds
    # v3 expects {"credentials": [{key, value}, ...]}
    return {"credentials": _creds_to_array(creds)}


def record_auth(
    api_base: str, workflow_args: dict, version: str = "v3", timeout: int = 30
) -> dict:
    """POST /auth and return the response JSON."""
    body = _build_auth_body(workflow_args, version)
    resp = requests.post(f"{api_base}/auth", json=body, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


def record_preflight(
    api_base: str, workflow_args: dict, version: str = "v3", timeout: int = 60
) -> dict:
    """POST /check and return the response JSON."""
    creds = workflow_args.get("credentials", {})
    metadata = workflow_args.get("metadata", {})
    if version == "v2":
        body = {**creds, "metadata": metadata}
    else:
        body = {
            "credentials": _creds_to_array(creds),
            "connection_config": {"metadata": metadata},
        }
    resp = requests.post(f"{api_base}/check", json=body, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


def record_metadata(
    api_base: str, workflow_args: dict, version: str = "v3", timeout: int = 60
) -> dict:
    """POST /metadata and return the response JSON."""
    body = _build_auth_body(workflow_args, version)
    resp = requests.post(f"{api_base}/metadata", json=body, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


def record_result(api_base: str, wf_id: str, timeout: int = 30) -> dict:
    """GET /result/{wf_id} and return the response JSON."""
    resp = requests.get(f"{api_base}/result/{wf_id}", timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


# ── Normalization ──────────────────────────────────────────────────────────


def normalize_api_response(response: dict) -> dict:
    """Replace dynamic values with placeholders, keeping keys and types intact."""
    return _normalize_obj(response)


def _normalize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        result = {}
        for k, v in sorted(obj.items()):
            if k in _DYNAMIC_PATTERNS:
                result[k] = _DYNAMIC_PATTERNS[k]
            elif k in _TIMESTAMP_KEYS:
                result[k] = "__TIMESTAMP__"
            elif k in _DURATION_KEYS:
                result[k] = 0
            else:
                result[k] = _normalize_obj(v)
        return result
    if isinstance(obj, list):
        return [_normalize_obj(item) for item in obj]
    if isinstance(obj, str):
        # Replace UUIDs and workflow ID patterns with placeholders
        s = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "__UUID__",
            obj,
        )
        return s
    return obj


# ── Persistence ────────────────────────────────────────────────────────────


def save_api_responses(out_dir: Path, responses: dict[str, dict]) -> None:
    """Save each endpoint response as {endpoint}.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for endpoint, data in responses.items():
        out_file = out_dir / f"{endpoint}.json"
        with open(out_file, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
    print(f"    Saved API responses: {', '.join(responses.keys())}")


def load_api_response(api_dir: Path, endpoint: str) -> dict | None:
    """Load a saved API response for a given endpoint."""
    path = api_dir / f"{endpoint}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
