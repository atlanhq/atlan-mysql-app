"""Integration tests for MySQLApp — embedded Temporal + embedded Dapr.

Tests the full extraction workflow through an in-process Temporal worker.
Credential resolution uses the real DaprCredentialVault path (same as
production), backed by an embedded Dapr sidecar with local-file storage.

No externally-installed Dapr or Temporal required. MySQL is provided via
testcontainers (or MYSQL_HOST env var).

Run tests with: uv run pytest tests/integration/ -v
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from application_sdk.contracts.types import ConnectionRef
from application_sdk.templates.contracts.sql_metadata import ExtractionInput
from app.mysql import MySQLApp, MySQLExtractionOutput

if TYPE_CHECKING:
    from tests.integration.conftest import AppExecutor

logger = logging.getLogger("integration.workflow")

_CONNECTION_NAME = "mysql-e2e-test"
_CONNECTION_QN = f"default/mysql/{_CONNECTION_NAME}"


class TestMySQLExtraction:
    """Full extraction workflow via embedded Temporal + embedded Dapr.

    Executes one workflow and shares the result across all tests in the class
    via a class-scoped fixture, avoiding the cost of re-running the extraction.
    """

    @pytest.fixture(scope="class")
    async def extraction_result(
        self,
        mysql_executor: "AppExecutor",
        mysql_credentials_files: str,
        store_root: Path,  # noqa: ARG002 — ensures store root is created
    ) -> MySQLExtractionOutput:
        """Execute a full extraction workflow, skip if no MySQL is available."""
        if not os.environ.get("MYSQL_HOST"):
            pytest.skip("No MySQL available — set MYSQL_HOST or provide Docker")

        result = cast(
            "MySQLExtractionOutput",
            await mysql_executor.execute_app(
                MySQLApp,
                ExtractionInput(
                    credential_guid=mysql_credentials_files,
                    connection=ConnectionRef.model_validate(
                        {
                            "typeName": "Connection",
                            "attributes": {
                                "qualifiedName": _CONNECTION_QN,
                                "name": _CONNECTION_NAME,
                            },
                        }
                    ),
                    include_filter="",
                ),
                execution_id_prefix=f"mysql-e2e-{uuid.uuid4().hex[:8]}",
            ),
        )
        return result

    async def test_workflow_completes(
        self, extraction_result: MySQLExtractionOutput
    ) -> None:
        """Workflow should complete and return a MySQLExtractionOutput."""
        assert extraction_result is not None
        assert isinstance(extraction_result, MySQLExtractionOutput)

    async def test_connection_qualified_name(
        self, extraction_result: MySQLExtractionOutput
    ) -> None:
        """Output should carry the connection qualified name."""
        assert extraction_result.connection_qualified_name
        assert "mysql" in extraction_result.connection_qualified_name

    async def test_transformed_data_prefix(
        self, extraction_result: MySQLExtractionOutput
    ) -> None:
        """Output should carry a non-empty transformed_data_prefix."""
        assert extraction_result.transformed_data_prefix

    async def test_raw_artifacts_exist(
        self,
        extraction_result: MySQLExtractionOutput,
        store_root: Path,
    ) -> None:
        """Raw JSONL files should exist for all four entity types.

        Files are preserved because APPLICATION_SDK_ENABLE_CLEANUP_INTERCEPTOR=false
        is set in conftest at load time.
        """
        raw_files = list(store_root.rglob("raw/database/records.json"))
        assert raw_files, (
            f"No raw/database/records.json found under {store_root}. "
            "Check that APPLICATION_SDK_ENABLE_CLEANUP_INTERCEPTOR=false."
        )
        run_dir = raw_files[0].parent.parent.parent  # .../raw/database/records.json

        for entity in ("database", "schema", "table", "column"):
            raw_file = run_dir / "raw" / entity / "records.json"
            assert raw_file.exists(), f"Missing raw/{entity}/records.json"
            assert raw_file.stat().st_size > 0, f"Empty raw/{entity}/records.json"

    async def test_transformed_artifacts_content(
        self,
        extraction_result: MySQLExtractionOutput,
        store_root: Path,
    ) -> None:
        """Transformed JSONL files should have valid Atlan entity shapes."""
        raw_files = list(store_root.rglob("raw/database/records.json"))
        assert raw_files, f"No raw/database/records.json found under {store_root}"
        run_dir = raw_files[0].parent.parent.parent

        for entity in ("database", "schema", "table", "column"):
            transformed_file = run_dir / "transformed" / entity / "entities.json"
            assert transformed_file.exists(), (
                f"Missing transformed/{entity}/entities.json"
            )

            lines = transformed_file.read_text().strip().splitlines()
            assert len(lines) > 0, f"Empty transformed/{entity}/entities.json"

            first = json.loads(lines[0])
            assert "typeName" in first, f"{entity} missing typeName"
            assert "attributes" in first, f"{entity} missing attributes"
            attrs = first["attributes"]
            assert "name" in attrs, f"{entity} missing attributes.name"
            assert "qualifiedName" in attrs, f"{entity} missing qualifiedName"
            assert attrs.get("connectorName") == "mysql", (
                f"{entity} connectorName != 'mysql'"
            )

    async def test_entity_type_names(
        self,
        extraction_result: MySQLExtractionOutput,
        store_root: Path,
    ) -> None:
        """Each entity type in transformed output should match allowed Atlas types."""
        raw_files = list(store_root.rglob("raw/database/records.json"))
        assert raw_files, f"No raw/database/records.json found under {store_root}"
        run_dir = raw_files[0].parent.parent.parent

        allowed_types = {
            "database": {"Database"},
            "schema": {"Schema"},
            "table": {"Table", "View"},
            "column": {"Column"},
        }
        for entity, allowed in allowed_types.items():
            transformed_file = run_dir / "transformed" / entity / "entities.json"
            if not transformed_file.exists():
                continue
            lines = transformed_file.read_text().strip().splitlines()
            seen = {json.loads(line)["typeName"] for line in lines}
            unexpected = seen - allowed
            assert not unexpected, (
                f"{entity} has unexpected typeName values: {unexpected}"
            )
