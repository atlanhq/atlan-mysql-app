"""Level 2A: API contract parity — compare v2 vs v3 HTTP response shapes.

Verifies that v3 API responses are structurally compatible with v2:
- All v2 keys are present in v3 (v3 may have additional keys)
- Value types match for shared keys
- Required fields exist in handler responses

Run:
  uv run pytest tests/parity/test_contract_parity.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from api_recorder import load_api_response

PARITY_DIR = Path(__file__).parent
OUTPUT_DIR = PARITY_DIR / "output"
ENDPOINTS = ["auth", "check", "metadata", "start", "status", "result"]

# Keys intentionally removed in v3 (not bugs — known API simplifications).
# Add a brief comment explaining why each field was dropped.
KNOWN_REMOVALS: set[str] = {
    "body.data.last_executed_run_id",  # v3 uses run_id for the same purpose
    # v2 error responses included raw exception details; v3 SDK wraps all
    # errors in {"success": false, "message": "..."} without these fields.
    "body.details",  # v2 auth error detail dict — replaced by body.message
    "body.error",  # v2 auth error string — replaced by body.message
    "body.detail",  # v2 validation/check error string — replaced by body.message
}

# Keys present in v3 that v2 never had — SDK v3 wraps all responses in a
# standard envelope.  These are intentional additions, not regressions.
KNOWN_ADDITIONS: set[str] = {
    "body.success",  # v3 SDK standard envelope field
    "body.data",  # v3 SDK standard envelope field
    "body.message",  # v3 SDK standard envelope field
    "body.correlation_id",  # v3 SDK request tracing field
}

# v3 SDK always returns HTTP 200 and wraps errors in {"success": false, ...}.
# v2 returned HTTP 4xx/5xx on auth failures and bad inputs.
# Flip this to False if v3 reverts to HTTP error codes.
V3_ALWAYS_200 = True


# ── Discovery ──────────────────────────────────────────────────────────────


def _discover_scenarios() -> list[str]:
    """Find scenarios that have both api_golden and api_v3 output."""
    found = []
    if not OUTPUT_DIR.is_dir():
        return found
    for d in sorted(OUTPUT_DIR.iterdir()):
        if not d.is_dir():
            continue
        has_golden = (d / "api_golden").is_dir()
        has_v3 = (d / "api_v3").is_dir()
        if has_golden and has_v3:
            found.append(d.name)
    return found


_SCENARIOS = _discover_scenarios()


def _has_capture(scenario: str, endpoint: str) -> bool:
    """True if *either* side captured a response for this scenario/endpoint."""
    return (OUTPUT_DIR / scenario / "api_golden" / f"{endpoint}.json").is_file() or (
        OUTPUT_DIR / scenario / "api_v3" / f"{endpoint}.json"
    ).is_file()


def _scenarios_with_endpoint(endpoint: str) -> list[str]:
    """Scenarios where at least one side captured `endpoint`.

    Used to parametrize TestHandlerContracts tests so they run exactly
    once per applicable scenario instead of skipping inapplicable combos
    (e.g. auth scenarios don't have ``check.json`` — no point running
    ``test_preflight_required_fields`` against them).
    """
    return [s for s in _SCENARIOS if _has_capture(s, endpoint)]


# Only cross-product combos where at least one side has a capture. Previous
# version parametrized every scenario × every endpoint and skipped the
# inapplicable combos at runtime — 300+ noisy skips. This keeps the signal
# (real asymmetries still fail via _assert_symmetric_capture) and drops the
# noise.
_PARAMS = [(s, e) for s in _SCENARIOS for e in ENDPOINTS if _has_capture(s, e)]
_IDS = [f"{s}-{e}" for s, e in _PARAMS]


# ── Shape Helpers ──────────────────────────────────────────────────────────


def _extract_shape(obj: Any) -> Any:
    """Extract structural shape: keys + value types, not actual values."""
    if isinstance(obj, dict):
        return {k: _extract_shape(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        if not obj:
            return ["empty"]
        return [_extract_shape(obj[0])]
    return type(obj).__name__


def _find_missing_keys(v2_obj: Any, v3_obj: Any, path: str = "") -> list[str]:
    """Recursively find keys present in v2 but missing from v3."""
    missing = []
    if isinstance(v2_obj, dict) and isinstance(v3_obj, dict):
        for key in v2_obj:
            full_path = f"{path}.{key}" if path else key
            if key not in v3_obj:
                missing.append(full_path)
            else:
                missing.extend(_find_missing_keys(v2_obj[key], v3_obj[key], full_path))
    return missing


def _find_type_mismatches(v2_obj: Any, v3_obj: Any, path: str = "") -> list[str]:
    """Recursively find keys where value types differ between v2 and v3."""
    mismatches = []
    if isinstance(v2_obj, dict) and isinstance(v3_obj, dict):
        for key in v2_obj:
            if key not in v3_obj:
                continue
            full_path = f"{path}.{key}" if path else key
            v2_val, v3_val = v2_obj[key], v3_obj[key]
            v2_type, v3_type = type(v2_val).__name__, type(v3_val).__name__
            # Allow int/float interchangeability
            numeric = {"int", "float"}
            if v2_type != v3_type and not ({v2_type, v3_type} <= numeric):
                # Allow None vs other type (optional fields)
                if v2_val is None or v3_val is None:
                    continue
                mismatches.append(f"{full_path}: v2={v2_type}, v3={v3_type}")
            else:
                mismatches.extend(_find_type_mismatches(v2_val, v3_val, full_path))
    return mismatches


# ── Tests ──────────────────────────────────────────────────────────────────


def _assert_symmetric_capture(scenario: str, endpoint: str, v2, v3) -> None:
    """Skip only when both sides agree a combo isn't applicable.

    - Both None → skip (legitimately nothing to compare; e.g. auth scenario
      has no ``check.json``).
    - One None → FAIL — one side produced a response and the other didn't.
      That's real divergence, not a not-applicable combo.
    """
    if v2 is None and v3 is None:
        pytest.skip(f"No API data for {scenario}/{endpoint}")
    assert v2 is not None, (
        f"[{scenario}/{endpoint}] v3 captured a response but v2 did not — "
        f"v3 added a response path without a v2 counterpart"
    )
    assert v3 is not None, (
        f"[{scenario}/{endpoint}] v2 captured a response but v3 did not — "
        f"v3 lost a response path v2 was emitting"
    )


class TestApiResponseStructure:
    """Compare structural shape of v2 vs v3 API responses.

    Strict mode (configured by request): every structural divergence fails.
    Only explicit ``KNOWN_REMOVALS`` entries are suppressed — add one with a
    justifying comment when a diff is confirmed intentional.
    """

    @pytest.mark.parametrize("scenario,endpoint", _PARAMS, ids=_IDS)
    def test_v3_has_all_v2_keys(self, scenario: str, endpoint: str) -> None:
        v2 = load_api_response(OUTPUT_DIR / scenario / "api_golden", endpoint)
        v3 = load_api_response(OUTPUT_DIR / scenario / "api_v3", endpoint)
        _assert_symmetric_capture(scenario, endpoint, v2, v3)
        assert v2 is not None and v3 is not None

        v2_status = v2.get("status_code", 200)
        v3_status = v3.get("status_code", 200)
        v2_is_error = v2_status >= 400
        v3_is_error = v3_status >= 400
        if V3_ALWAYS_200 and v2_is_error and not v3_is_error:
            pass  # expected: v3 SDK always returns HTTP 200; failures use body.success=false
        else:
            assert v2_is_error == v3_is_error, (
                f"[{scenario}/{endpoint}] HTTP status-code divergence: "
                f"v2={v2_status}, v3={v3_status}"
            )

        missing = [k for k in _find_missing_keys(v2, v3) if k not in KNOWN_REMOVALS]
        assert not missing, (
            f"[{scenario}/{endpoint}] v3 missing {len(missing)} keys from v2:\n"
            + "\n".join(f"  {k}" for k in missing[:20])
        )

    @pytest.mark.parametrize("scenario,endpoint", _PARAMS, ids=_IDS)
    def test_v2_has_all_v3_keys(self, scenario: str, endpoint: str) -> None:
        """Reverse direction — v2 must also have every key v3 has.

        Catches v3 growing undocumented fields. Allowlist intentional v3
        additions in ``KNOWN_ADDITIONS`` (SDK envelope fields that v2 never had).
        """
        v2 = load_api_response(OUTPUT_DIR / scenario / "api_golden", endpoint)
        v3 = load_api_response(OUTPUT_DIR / scenario / "api_v3", endpoint)
        _assert_symmetric_capture(scenario, endpoint, v2, v3)

        # Swap args: find keys in v3 missing from v2.
        # Exclude known SDK v3 additions (envelope fields) and known removals.
        allowlisted = KNOWN_REMOVALS | KNOWN_ADDITIONS
        extra = [k for k in _find_missing_keys(v3, v2) if k not in allowlisted]
        assert not extra, (
            f"[{scenario}/{endpoint}] v3 has {len(extra)} keys absent from v2:\n"
            + "\n".join(f"  {k}" for k in extra[:20])
        )

    @pytest.mark.parametrize("scenario,endpoint", _PARAMS, ids=_IDS)
    def test_value_types_match(self, scenario: str, endpoint: str) -> None:
        v2 = load_api_response(OUTPUT_DIR / scenario / "api_golden", endpoint)
        v3 = load_api_response(OUTPUT_DIR / scenario / "api_v3", endpoint)
        _assert_symmetric_capture(scenario, endpoint, v2, v3)

        mismatches = _find_type_mismatches(v2, v3)
        assert not mismatches, (
            f"[{scenario}/{endpoint}] {len(mismatches)} type mismatches:\n"
            + "\n".join(f"  {m}" for m in mismatches[:20])
        )


def _load_v3_or_fail(scenario: str, endpoint: str) -> dict:
    """Load the v3 response for (scenario, endpoint); fail if absent.

    The caller is already parametrized via ``_scenarios_with_endpoint``, so
    *either* v2 or v3 had a capture. If v3's side is missing, that's a
    real gap: v2 emitted a response and v3 didn't.
    """
    v3 = load_api_response(OUTPUT_DIR / scenario / "api_v3", endpoint)
    assert (
        v3 is not None
    ), f"[{scenario}/{endpoint}] v2 captured a response but v3 did not"
    return v3


_AUTH_SCENARIOS = _scenarios_with_endpoint("auth")
_CHECK_SCENARIOS = _scenarios_with_endpoint("check")
_METADATA_SCENARIOS = _scenarios_with_endpoint("metadata")
_START_SCENARIOS = _scenarios_with_endpoint("start")
_STATUS_SCENARIOS = _scenarios_with_endpoint("status")


class TestHandlerContracts:
    """Verify required fields exist in v3 handler responses.

    Each test parametrizes *only* on scenarios that actually captured the
    relevant endpoint — see ``_scenarios_with_endpoint``. Asymmetric
    captures (v2 has it, v3 doesn't) fail via ``_load_v3_or_fail``.
    """

    @pytest.mark.parametrize("scenario", _AUTH_SCENARIOS)
    def test_auth_required_fields(self, scenario: str) -> None:
        v3 = _load_v3_or_fail(scenario, "auth")
        body = v3.get("body", {})
        assert "success" in body, f"[{scenario}] auth response missing 'success'"
        assert (
            "message" in body or "data" in body
        ), f"[{scenario}] auth response missing 'message' or 'data'"

    @pytest.mark.parametrize("scenario", _CHECK_SCENARIOS)
    def test_preflight_required_fields(self, scenario: str) -> None:
        v3 = _load_v3_or_fail(scenario, "check")
        body = v3.get("body", {})
        assert "success" in body, f"[{scenario}] check response missing 'success'"
        if body.get("success"):
            data = body.get("data", {})
            assert isinstance(
                data, dict
            ), f"[{scenario}] check response.data should be dict"

    @pytest.mark.parametrize("scenario", _METADATA_SCENARIOS)
    def test_metadata_required_fields(self, scenario: str) -> None:
        v3 = _load_v3_or_fail(scenario, "metadata")
        body = v3.get("body", {})
        assert "success" in body, f"[{scenario}] metadata response missing 'success'"
        if body.get("success"):
            data = body.get("data", {})
            assert isinstance(
                data, (dict, list)
            ), f"[{scenario}] metadata response.data should be dict or list"

    @pytest.mark.parametrize("scenario", _START_SCENARIOS)
    def test_start_required_fields(self, scenario: str) -> None:
        v3 = _load_v3_or_fail(scenario, "start")
        body = v3.get("body", {})
        assert (
            body.get("success") is True
        ), f"[{scenario}] start response not successful"
        data = body.get("data", {})
        assert "workflow_id" in data or "workflow_id" in str(
            data
        ), f"[{scenario}] start response missing workflow_id"

    @pytest.mark.parametrize("scenario", _STATUS_SCENARIOS)
    def test_status_required_fields(self, scenario: str) -> None:
        v3 = _load_v3_or_fail(scenario, "status")
        body = v3.get("body", {})
        data = body.get("data", {})
        assert "status" in data, f"[{scenario}] status response missing 'status' field"
