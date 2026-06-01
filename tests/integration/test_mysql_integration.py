"""Integration tests for the MySQL connector.

PLACEHOLDER — extend scenarios per the write-and-deploy-integration-tests
skill once the connector team confirms credentials shape + a test source.
"""

from __future__ import annotations

import os

from application_sdk.testing.integration import BaseIntegrationTest, Scenario, equals, lazy


def load_basic_credentials() -> dict:
    return {
        "host": os.environ.get("E2E_MYSQL_HOST", ""),
        "port": os.environ.get("E2E_MYSQL_PORT", "3306"),
        "username": os.environ.get("E2E_MYSQL_USERNAME", ""),
        "password": os.environ.get("E2E_MYSQL_PASSWORD", ""),
        "extra": {
            "database": os.environ.get("E2E_MYSQL_DATABASE", ""),
        },
        "authType": "basic",
    }


class TestMySQLIntegration(BaseIntegrationTest):
    default_credentials = {"authType": "basic", "type": "all"}
    default_metadata = {
        "include-filter": "{}",
        "exclude-filter": "{}",
        "temp-table-regex": "",
        "extraction-method": "direct",
    }
    default_connection = {
        "connection_name": "test_mysql_integration",
        "connection_qualified_name": "default/mysql/test_integration",
    }

    scenarios = [
        Scenario(
            name="auth_valid_credentials",
            api="auth",
            args=lazy(lambda: {"credentials": load_basic_credentials()}),
            assert_that={
                "success": equals(True),
            },
        ),
    ]
