"""Fixtures for integration tests.

Tests run entirely in-process: Temporal starts as an embedded dev server via
the SDK's ``embedded_runtime()``, and a Dapr sidecar starts as a subprocess
via the SDK's cached daprd binary — no externally-installed Dapr or Temporal
required.

Credential resolution follows the identical code path as production:
  DaprCredentialVault
    ├── objectstore GET  →  bindings.localstorage (temp dir)
    └── GetSecret        →  secretstores.local.file (temp JSON file, multiValued)

``ATLAN_DEPLOYMENT_NAME=ci`` (set before SDK imports) tells the SDK to use the
full Dapr API for both legs, bypassing the LOCAL_ENVIRONMENT short-circuit in
``_get_secret()`` that would otherwise read the secrets file directly.

The MySQL testcontainers fixture still requires Docker to be available.

Run tests with: uv run pytest tests/integration/ -v
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# SDK-affecting env vars MUST be set before any application_sdk import so that
# module-level constants (APPLICATION_NAME, DEPLOYMENT_NAME) read correctly.
#
# ATLAN_DEPLOYMENT_NAME=ci  — any value other than "local" causes
#   DaprCredentialVault._get_secret() to call the Dapr secret store API
#   instead of reading ./local/dapr/secrets/secrets.json directly.
#   With secretstores.local.file + multiValued=true we get the full
#   production code path without any short-circuit.
# ---------------------------------------------------------------------------
os.environ.setdefault("ATLAN_APPLICATION_NAME", "mysql")
os.environ.setdefault("ATLAN_DEPLOYMENT_NAME", "ci")

import docker
import pymysql
import pymysql.constants.CLIENT
import pytest
import pytest_asyncio
from application_sdk.app.context import AppContext
from application_sdk.dev import embedded_runtime
from application_sdk.dev._dapr import (
    _ensure_daprd_binary,
    _pick_free_port,
    _wait_for_dapr_ready,
)
from application_sdk.execution._temporal.backend import TemporalExecutorBackend
from application_sdk.execution._temporal.converter import create_data_converter_for_app
from application_sdk.execution._temporal.worker import create_worker
from application_sdk.execution.retry import RetryPolicy
from application_sdk.infrastructure.context import (
    InfrastructureContext,
    set_infrastructure,
)
from application_sdk.observability.observability import AtlanObservability
from application_sdk.storage import create_local_store, create_memory_store
from application_sdk.testing.mocks import MockSecretStore, MockStateStore
from temporalio.client import Client
from testcontainers.mysql import MySqlContainer

# Trigger MySQLApp registration before create_worker is called.
from app.mysql import MySQLApp  # noqa: F401

# Pre-wire a memory store so the periodic observability flush does not keep
# retrying and spamming warnings in tests.
AtlanObservability._deployment_store = create_memory_store()

# Preserve workflow artifacts for integration test validation.
# Without this, the SDK's cleanup interceptor deletes FileReference-tracked
# files after each workflow completes, making artifact assertions impossible.
os.environ.setdefault("APPLICATION_SDK_ENABLE_CLEANUP_INTERCEPTOR", "false")

_TASK_QUEUE = "mysql-queue"
_TEST_CREDENTIAL_GUID = "test-mysql-cred"

PROJECT_ROOT = Path(__file__).parent.parent.parent
SEED_SQL = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "seed.sql"

logger = logging.getLogger("integration")

# ---------------------------------------------------------------------------
# Dapr component YAML templates
# ---------------------------------------------------------------------------

_COMPONENT_STATESTORE = """\
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: statestore
spec:
  type: state.in-memory
  version: v1
  metadata: []
"""

_COMPONENT_SECRETSTORE_TMPL = """\
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: {name}
spec:
  type: secretstores.local.file
  version: v1
  metadata:
    - name: secretsFile
      value: {secrets_file}
    - name: multiValued
      value: "true"
"""

_COMPONENT_LOCALSTORAGE_TMPL = """\
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: {name}
spec:
  type: bindings.localstorage
  version: v1
  metadata:
    - name: rootPath
      value: {root_path}
"""


class AppExecutor:
    """Compatibility shim wrapping TemporalExecutorBackend for integration tests."""

    def __init__(self, backend: TemporalExecutorBackend) -> None:
        self._backend = backend

    async def execute_app(
        self,
        app_cls: Any,
        input_data: Any,
        *,
        execution_id_prefix: str = "",
    ) -> Any:
        app_name = getattr(app_cls, "_app_name", execution_id_prefix or "app")
        context = AppContext(
            app_name=app_name,
            app_version="0.0.0",
            run_id=execution_id_prefix or app_name,
        )
        return await self._backend.execute(
            app_cls,
            input_data,
            context=context,
            retry_policy=RetryPolicy(),
        )


# ---------------------------------------------------------------------------
# MySQL database fixture (testcontainers or external)
# ---------------------------------------------------------------------------


def _mysql_host_preconfigured() -> bool:
    """Check if MySQL connection is already configured via env vars."""
    return bool(os.environ.get("MYSQL_HOST"))


def _docker_available() -> bool:
    """Check if Docker daemon is reachable."""
    try:
        docker.from_env().ping()
        return True
    except Exception:
        logger.debug("Docker daemon not reachable", exc_info=True)
        return False


@pytest.fixture(scope="session", autouse=True)
def mysql_database():
    """Provide a MySQL database for integration tests.

    Priority:
    1. MYSQL_HOST env var set → use external database
    2. Docker available → start MySQL via testcontainers with seed data
    3. Neither → yield without MySQL (workflow tests will skip)
    """
    if _mysql_host_preconfigured():
        logger.info("Using preconfigured MySQL at %s", os.environ["MYSQL_HOST"])
        yield
        return

    if not _docker_available():
        logger.warning("No MYSQL_HOST and no Docker — testcontainers unavailable")
        yield
        return

    root_password = "rootpass"
    logger.info("Starting MySQL container via testcontainers...")
    mysql = MySqlContainer(
        image="mysql:8.0",
        username="testuser",
        password="testpass",
        root_password=root_password,
        dbname="ecommerce",
    )

    with mysql:
        host = mysql.get_container_host_ip()
        port = mysql.get_exposed_port(3306)

        os.environ["MYSQL_HOST"] = host
        os.environ["MYSQL_PORT"] = str(port)
        os.environ["MYSQL_USER"] = "root"
        os.environ["MYSQL_PASSWORD"] = root_password

        logger.info("MySQL container ready at %s:%s", host, port)

        if SEED_SQL.exists():
            _seed_database(host, int(port), root_password)

        yield

        for key in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD"):
            os.environ.pop(key, None)


def _seed_database(host: str, port: int, root_password: str = "rootpass"):
    """Execute seed SQL against the testcontainers MySQL instance."""
    logger.info("Seeding database from %s...", SEED_SQL.name)
    conn = pymysql.connect(
        host=host,
        port=port,
        user="root",
        password=root_password,
        connect_timeout=30,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(SEED_SQL.read_text())

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_SCHEMA, COUNT(*) "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys') "
                "GROUP BY TABLE_SCHEMA"
            )
            for schema, count in cursor.fetchall():
                logger.info("  %s: %d tables", schema, count)
    finally:
        conn.close()
    logger.info("Seeding complete")


# ---------------------------------------------------------------------------
# Embedded Dapr sidecar with secretstores.local.file
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def dapr_secrets_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Temp JSON file used as the secretstores.local.file secrets source.

    The file path is passed to the Dapr component YAML so daprd serves
    its contents via the GetSecret API. Structured as:
        {"<guid>": {"username": "...", "password": "..."}}
    With multiValued=true, GetSecret("<guid>") returns the nested object.
    """
    return tmp_path_factory.mktemp("dapr-secrets") / "secrets.json"


@pytest.fixture(scope="session")
def dapr_objectstore_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Temp directory used as the objectstore root for the embedded Dapr sidecar.

    Credential config files (non-sensitive fields: host, port, authType) are
    written here; the localstorage binding serves them on GET requests from
    DaprCredentialVault._fetch_credential_config().
    """
    return tmp_path_factory.mktemp("dapr-objectstore")


@pytest.fixture(scope="session")
def mysql_credentials_files(
    mysql_database,  # noqa: ARG001 — ensures MYSQL_HOST/PORT/USER/PASSWORD are set
    dapr_secrets_file: Path,
    dapr_objectstore_dir: Path,
) -> str:
    """Write MySQL credential files for DaprCredentialVault resolution.

    Replicates what ``POST /workflows/v1/dev/local-vault`` does, directly:

    Objectstore (non-sensitive: host, port, authType) →
        ``{dapr_objectstore_dir}/persistent-artifacts/apps/mysql/
          credentials/{guid}/config.json``
        served by Dapr's bindings.localstorage on GET.

    Secrets file (sensitive: username, password) →
        ``{dapr_secrets_file}`` as ``{"<guid>": {"username": ..., "password": ...}}``
        served by Dapr's secretstores.local.file on GetSecret("<guid>").
    """
    guid = _TEST_CREDENTIAL_GUID

    # Write non-sensitive config to the objectstore directory.
    config = {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "port": os.environ.get("MYSQL_PORT", "3306"),
        "authType": "basic",
        "credentialSource": "direct",
    }
    config_path = (
        dapr_objectstore_dir
        / "persistent-artifacts"
        / "apps"
        / "mysql"
        / "credentials"
        / guid
        / "config.json"
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config))

    # Write sensitive fields to the secrets JSON file.
    # With multiValued=true, GetSecret(guid) returns the nested object directly.
    secrets = {
        guid: {
            "username": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", ""),
        }
    }
    dapr_secrets_file.write_text(json.dumps(secrets, indent=2))

    return guid


@pytest_asyncio.fixture(scope="session")
async def embedded_dapr_sidecar(
    mysql_credentials_files: str,  # noqa: ARG001 — ensures files are written before daprd starts
    dapr_secrets_file: Path,
    dapr_objectstore_dir: Path,
):
    """Start a daprd sidecar with secretstores.local.file for credential resolution.

    Uses the SDK's cached daprd binary (downloaded once to ~/.cache/atlan-sdk/dapr/).
    Configures secretstores.local.file (multiValued=true) so DaprCredentialVault
    can call GetSecret(guid) through the full Dapr API — no SDK short-circuit.
    Sets DAPR_HTTP_PORT, DAPR_GRPC_PORT, and DAPR_COMPONENTS_PATH so
    AsyncDaprClient() (instantiated inside DaprCredentialVault) connects here.
    """
    binary = _ensure_daprd_binary()
    http_port = _pick_free_port()
    grpc_port = _pick_free_port()

    components_dir = Path(tempfile.mkdtemp(prefix="atlan-dapr-components-"))
    eventstore_dir = Path(tempfile.mkdtemp(prefix="atlan-dapr-events-"))

    secrets_file_abs = str(dapr_secrets_file.resolve())
    objectstore_root_abs = str(dapr_objectstore_dir.resolve())

    (components_dir / "statestore.yaml").write_text(_COMPONENT_STATESTORE)
    (components_dir / "secretstore.yaml").write_text(
        _COMPONENT_SECRETSTORE_TMPL.format(
            name="secretstore", secrets_file=secrets_file_abs
        )
    )
    (components_dir / "deployment-secret-store.yaml").write_text(
        _COMPONENT_SECRETSTORE_TMPL.format(
            name="deployment-secret-store", secrets_file=secrets_file_abs
        )
    )
    (components_dir / "objectstore.yaml").write_text(
        _COMPONENT_LOCALSTORAGE_TMPL.format(
            name="objectstore", root_path=objectstore_root_abs
        )
    )
    (components_dir / "eventstore.yaml").write_text(
        _COMPONENT_LOCALSTORAGE_TMPL.format(
            name="eventstore", root_path=str(eventstore_dir)
        )
    )

    prev_env = {
        k: os.environ.get(k)
        for k in ("DAPR_HTTP_PORT", "DAPR_GRPC_PORT", "DAPR_COMPONENTS_PATH")
    }
    os.environ["DAPR_HTTP_PORT"] = str(http_port)
    os.environ["DAPR_GRPC_PORT"] = str(grpc_port)
    os.environ["DAPR_COMPONENTS_PATH"] = str(components_dir)

    logger.info("Starting embedded daprd (http=%d grpc=%d)", http_port, grpc_port)
    proc = await asyncio.create_subprocess_exec(
        str(binary),
        "--app-id",
        "mysql",
        "--dapr-http-port",
        str(http_port),
        "--dapr-grpc-port",
        str(grpc_port),
        "--resources-path",
        str(components_dir),
        "--log-level",
        "error",
        "--enable-metrics=false",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    try:
        await _wait_for_dapr_ready(http_port)
        logger.info("Embedded daprd ready at http://127.0.0.1:%d", http_port)
        yield
    finally:
        logger.info("Shutting down embedded daprd")
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        shutil.rmtree(components_dir, ignore_errors=True)
        shutil.rmtree(eventstore_dir, ignore_errors=True)
        for k, v in prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Infrastructure fixture — state store + object storage (not for credentials)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def store_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Root directory for the session-scoped LocalStore.

    Files written by the workflow (raw JSONL, transformed JSONL) survive here
    because APPLICATION_SDK_ENABLE_CLEANUP_INTERCEPTOR=false is set above.
    Tests can locate artifacts by recursively searching this directory.
    """
    return tmp_path_factory.mktemp("sdk-store")


@pytest.fixture(scope="session")
def infrastructure(store_root: Path) -> InfrastructureContext:
    """Wire mock infrastructure for the session using a LocalStore.

    Sets the global InfrastructureContext so SDK internals (storage ops, state
    store) use in-process stores. Credential resolution is handled separately
    by DaprCredentialVault talking to the embedded Dapr sidecar.
    """
    ctx = InfrastructureContext(
        state_store=MockStateStore(),
        secret_store=MockSecretStore(),
        storage=create_local_store(store_root),
    )
    set_infrastructure(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Embedded Temporal runtime
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def embedded_temporal():
    """Boot an in-process Temporal dev server for the test session."""
    async with embedded_runtime(log_level="error") as rt:
        yield rt


# ---------------------------------------------------------------------------
# Temporal client and in-process worker fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def temporal_client(embedded_temporal) -> Client:
    """Connect to the embedded Temporal dev server."""
    data_converter = create_data_converter_for_app(MySQLApp)
    return await Client.connect(embedded_temporal.host, data_converter=data_converter)


@pytest_asyncio.fixture(scope="session")
async def mysql_worker(
    temporal_client: Client,
    infrastructure: InfrastructureContext,  # noqa: ARG001 — ensures infra is wired first
) -> Any:
    """Start the MySQL connector worker in-process."""
    w = create_worker(temporal_client, task_queue=_TASK_QUEUE)
    async with w:
        yield


@pytest.fixture(scope="session")
def mysql_executor(
    temporal_client: Client,
    mysql_worker: Any,  # noqa: ARG001 — ensures worker is running
    embedded_dapr_sidecar: Any,  # noqa: ARG001 — ensures DAPR_HTTP_PORT is set
) -> AppExecutor:
    """Executor for MySQL connector integration tests.

    Depends on embedded_dapr_sidecar so DAPR_HTTP_PORT is set before any
    workflow attempts credential resolution via DaprCredentialVault.
    """
    backend = TemporalExecutorBackend(
        client=temporal_client,
        task_queue=_TASK_QUEUE,
    )
    return AppExecutor(backend=backend)
