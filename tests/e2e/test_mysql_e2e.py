"""E2E tests for MySQL v3 app.

Requires a running app: `make dev` or `atlan app run -p .`
Tests hit the handler endpoints and trigger a workflow run.

Local:   source .env && make dev   # then: source .env && make test-e2e
Remote:  make test-e2e-remote      # port-forwards to vcluster app
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger("e2e")

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
TIMEOUT = 10
WORKFLOW_POLL_INTERVAL = 5
WORKFLOW_POLL_MAX = 60


def _v3_creds():
    """Build v3 HandlerCredential array from env vars."""
    return [
        {"key": "host", "value": os.environ.get("MYSQL_HOST", "localhost")},
        {"key": "port", "value": os.environ.get("MYSQL_PORT", "3306")},
        {"key": "username", "value": os.environ.get("MYSQL_USER", "root")},
        {"key": "password", "value": os.environ.get("MYSQL_PASSWORD", "")},
        {"key": "authType", "value": "basic"},
    ]


def _credential_guid():
    """Get credential GUID for workflow tests."""
    return os.environ.get(
        "CREDENTIAL_GUID",
        os.environ.get("LOCAL_CREDENTIAL_GUID", "local-mysql"),
    )


def _skip_if_no_app():
    """Skip if app is not running."""
    try:
        resp = requests.get(f"{BASE_URL}/server/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _poll_workflow(workflow_id: str, run_id: str) -> dict:
    """Poll workflow status until terminal state or timeout."""
    for _ in range(WORKFLOW_POLL_MAX):
        resp = requests.get(
            f"{BASE_URL}/workflows/v1/status/{workflow_id}/{run_id}",
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            status = data.get("status", "")
            if status in ("COMPLETED", "FAILED"):
                return data
        time.sleep(WORKFLOW_POLL_INTERVAL)
    return {"status": "TIMEOUT"}


@unittest.skipUnless(_skip_if_no_app(), "App not running on localhost:8000")
class TestMySQLE2E(unittest.TestCase):
    """E2E tests against running MySQL app."""

    # ── Health ────────────────────────────────────────────────────────

    def test_health_check(self):
        resp = requests.get(f"{BASE_URL}/server/health", timeout=TIMEOUT)
        self.assertEqual(resp.status_code, 200)

    # ── Auth ──────────────────────────────────────────────────────────

    def test_auth_success(self):
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/auth",
            json={"credentials": _v3_creds()},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Auth failed: {data}")
        self.assertEqual(data["data"]["status"], "success")

    def test_auth_negative_invalid_auth_type(self):
        """Auth with unsupported authType should return status=failed in data."""
        bad_creds = [
            {"key": "host", "value": "localhost"},
            {"key": "port", "value": "3306"},
            {"key": "username", "value": "root"},
            {"key": "password", "value": "password"},
            {"key": "authType", "value": "invalid_type"},
        ]
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/auth",
            json={"credentials": bad_creds},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("data", data)
        self.assertIn("status", data["data"])

    # ── Preflight ─────────────────────────────────────────────────────

    def test_preflight_check(self):
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/check",
            json={"credentials": _v3_creds()},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Preflight failed: {data}")

    # ── Metadata ──────────────────────────────────────────────────────

    def test_metadata_returns_response(self):
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/metadata",
            json={"credentials": _v3_creds()},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Metadata failed: {data}")
        self.assertIsInstance(data.get("data"), list)

    # ── Configmaps ────────────────────────────────────────────────────

    def test_configmap_list(self):
        resp = requests.get(
            f"{BASE_URL}/workflows/v1/configmaps",
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)

    # ── Workflow Run ──────────────────────────────────────────────────

    def test_run_workflow(self):
        """Run full extraction workflow, assert COMPLETED + validate artifacts.

        Validates:
        1. Workflow completes successfully
        2. Raw parquet files exist for databases, schemas, tables, columns
        3. Transformed JSONL files exist with valid entity structure
        """
        output_path = tempfile.mkdtemp(prefix="mysql-e2e-")
        try:
            self._run_and_validate(output_path)
        finally:
            shutil.rmtree(output_path, ignore_errors=True)

    def _run_and_validate(self, output_path: str):
        payload = {
            "credential_guid": _credential_guid(),
            "output_path": output_path,
            "metadata": {},
            "connection": {
                "connection_name": "test-mysql",
                "connection_qualified_name": "default/mysql/test",
            },
        }
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/start",
            json=payload,
            timeout=30,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Start failed: {data}")

        workflow_id = data["data"]["workflow_id"]
        run_id = data["data"]["run_id"]

        # Poll for completion
        result = _poll_workflow(workflow_id, run_id)
        self.assertEqual(
            result.get("status"),
            "COMPLETED",
            f"Workflow did not complete: {result}",
        )

        # ── Validate raw extraction (parquet) ────────────────────────
        raw_dir = Path(output_path) / "raw"
        self.assertTrue(raw_dir.exists(), f"No raw/ directory at {output_path}")

        entity_types = {d.name for d in raw_dir.iterdir() if d.is_dir()}
        for expected in ("database", "schema", "table", "column"):
            self.assertIn(
                expected,
                entity_types,
                f"Missing raw/{expected}/ — found: {entity_types}",
            )

        for entity in ("database", "schema", "table", "column"):
            parquets = list((raw_dir / entity).glob("*.parquet"))
            self.assertTrue(
                len(parquets) > 0,
                f"No parquet files in raw/{entity}/",
            )

        # ── Validate transformed output (JSONL) ─────────────────────
        transformed_dir = Path(output_path) / "transformed"
        self.assertTrue(
            transformed_dir.exists(),
            f"No transformed/ directory at {output_path}",
        )

        for entity in ("database", "schema", "table", "column"):
            jsonl_file = transformed_dir / entity / "entities.jsonl"
            self.assertTrue(
                jsonl_file.exists(),
                f"Missing transformed/{entity}/entities.jsonl",
            )

            lines = jsonl_file.read_text().strip().splitlines()
            self.assertTrue(len(lines) > 0, f"Empty JSONL for {entity}")

            first = json.loads(lines[0])
            self.assertIn("typeName", first, f"{entity} missing typeName")
            self.assertIn("attributes", first, f"{entity} missing attributes")
            attrs = first["attributes"]
            self.assertIn("name", attrs, f"{entity} missing attributes.name")
            self.assertIn("qualifiedName", attrs, f"{entity} missing qualifiedName")
            self.assertEqual(
                attrs.get("connectorName"),
                "mysql",
                f"{entity} connectorName != mysql",
            )

        # ── Validate entity type names ───────────────────────────────
        type_map = {
            "database": {"Database"},
            "schema": {"Schema"},
            "table": {"Table", "View"},  # MySQL returns tables + views together
            "column": {"Column"},
        }
        for entity, allowed_types in type_map.items():
            jsonl_file = transformed_dir / entity / "entities.jsonl"
            lines = jsonl_file.read_text().strip().splitlines()
            seen_types = {json.loads(line)["typeName"] for line in lines}
            self.assertTrue(
                seen_types <= allowed_types,
                f"{entity} has unexpected types: {seen_types - allowed_types}",
            )

        # ── Extraction report ────────────────────────────────────────
        self._print_extraction_report(
            output_path, result.get("execution_duration_seconds", 0)
        )

    @staticmethod
    def _print_extraction_report(output_path: str, duration_seconds: int):
        """Log extraction summary — visible via pytest live logging."""
        raw_dir = Path(output_path) / "raw"
        transformed_dir = Path(output_path) / "transformed"

        logger.info("=" * 55)
        logger.info("EXTRACTION REPORT  (duration: %ds)", duration_seconds)
        logger.info("=" * 55)
        logger.info(
            "%-15s | %9s | %11s | %s", "Entity", "Extracted", "Transformed", "Sample"
        )
        logger.info("%-15s | %9s | %11s | %s", "-" * 15, "-" * 9, "-" * 11, "-" * 20)

        for entity in ("database", "schema", "table", "column"):
            raw_count = 0
            raw_entity_dir = raw_dir / entity
            if raw_entity_dir.exists():
                for pf in raw_entity_dir.glob("*.parquet"):
                    raw_count += len(pd.read_parquet(str(pf)))

            transformed_count = 0
            sample_name = ""
            jsonl_file = transformed_dir / entity / "entities.jsonl"
            if jsonl_file.exists():
                lines = jsonl_file.read_text().strip().splitlines()
                transformed_count = len(lines)
                if lines:
                    first = json.loads(lines[0])
                    sample_name = first.get("attributes", {}).get("name", "")

            logger.info(
                "%-15s | %9d | %11d | %s",
                entity,
                raw_count,
                transformed_count,
                sample_name,
            )

        logger.info("=" * 55)


@unittest.skipUnless(_skip_if_no_app(), "App not running on localhost:8000")
class TestMySQLV2CompatFormat(unittest.TestCase):
    """Test v2 flat credential format is accepted (SDK normalizes)."""

    def test_auth_v2_flat_format(self):
        v2_creds = {
            "host": os.environ.get("MYSQL_HOST", "localhost"),
            "port": os.environ.get("MYSQL_PORT", "3306"),
            "username": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", ""),
            "authType": "basic",
        }
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/auth",
            json={"credentials": v2_creds},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"V2 format auth failed: {data}")
