"""E2E tests for MySQL v3 app.

Requires a running app: `make dev` or `atlan app run -p .`
Tests hit the handler endpoints and trigger a workflow run.

Run: `make test-e2e`
"""

from __future__ import annotations

import os
import time
import unittest

import requests

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
TIMEOUT = 10


def _v3_creds():
    """Build v3 HandlerCredential array from env vars."""
    return [
        {"key": "host", "value": os.environ.get("MYSQL_HOST", "localhost")},
        {"key": "port", "value": os.environ.get("MYSQL_PORT", "3306")},
        {"key": "username", "value": os.environ.get("MYSQL_USER", "root")},
        {"key": "password", "value": os.environ.get("MYSQL_PASSWORD", "")},
        {"key": "authType", "value": "basic"},
    ]


def _skip_if_no_app():
    """Skip if app is not running."""
    try:
        resp = requests.get(f"{BASE_URL}/server/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


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

    def test_auth_negative_empty_credentials(self):
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/auth",
            json={"credentials": []},
            timeout=TIMEOUT,
        )
        data = resp.json()
        self.assertFalse(data.get("success"))

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
        checks = data.get("data", {})
        self.assertTrue(len(checks) > 0, "No preflight checks returned")

    # ── Metadata ──────────────────────────────────────────────────────

    def test_metadata_returns_schemas(self):
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/metadata",
            json={"credentials": _v3_creds()},
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Metadata failed: {data}")
        objects = data.get("data", [])
        self.assertIsInstance(objects, list)
        # Should return at least the system schemas
        self.assertTrue(len(objects) > 0, "No schemas returned")

    # ── Configmaps ────────────────────────────────────────────────────

    def test_configmap_list(self):
        resp = requests.get(
            f"{BASE_URL}/workflows/v1/configmaps",
            timeout=TIMEOUT,
        )
        self.assertEqual(resp.status_code, 200)

    # ── Workflow Run ──────────────────────────────────────────────────

    def test_run_workflow(self):
        """Trigger a full extraction workflow and wait for completion."""
        payload = {
            "credentials": _v3_creds(),
            "metadata": {},
            "connection": {"connection_name": "test-mysql", "connection_qualified_name": "default/mysql/test"},
        }
        resp = requests.post(
            f"{BASE_URL}/workflows/v1/start",
            json=payload,
            timeout=30,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"), f"Start failed: {data}")

        workflow_id = data.get("data", {}).get("workflow_id")
        run_id = data.get("data", {}).get("run_id")

        if workflow_id and run_id:
            # Poll for completion
            for _ in range(60):
                status_resp = requests.get(
                    f"{BASE_URL}/workflows/v1/status/{workflow_id}/{run_id}",
                    timeout=TIMEOUT,
                )
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    status = status_data.get("data", {}).get("status", "")
                    if status in ("COMPLETED", "FAILED"):
                        self.assertEqual(
                            status, "COMPLETED", f"Workflow failed: {status_data}"
                        )
                        return
                time.sleep(5)

            self.fail("Workflow did not complete within timeout")


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
