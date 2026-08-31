"""Integration conftest: the SDK's shared fixture kit plus mysql's real-Dapr leg.

Everything the kit owns — embedded Temporal, client, in-process worker,
executor shim, task-queue derivation, artifact preservation — comes from the
star-import of ``application_sdk.testing.integration.fixtures``. This file
keeps only what is genuinely mysql's:

* ``integration_source`` — a seeded MySQL testcontainer, with the MYSQL_HOST
  escape hatch (external database) and the no-Docker skip path preserved.
* The real ``DaprCredentialVault`` credential path. Workflow inputs here route
  by legacy ``credential_guid``, which resolves over a live daprd and never
  reads the kit's ``MockSecretStore``, so ``infrastructure`` is overridden: it
  writes component YAMLs (secretstores.local.file in multiValued mode plus a
  localstorage objectstore), starts the SDK's ``embedded_dapr`` sidecar, and
  wraps the kit's own body via ``kit_infrastructure`` so the mocked
  state/secret/object stores and the observability-store swap stay intact.
  The override is async because ``embedded_dapr`` is an async contextmanager;
  the kit's async fixtures already pin ``loop_scope="session"``, and this one
  matches. ``worker`` depends on ``infrastructure``, so daprd is up and
  DAPR_HTTP_PORT is set before any workflow attempts credential resolution.

Credential resolution follows the identical code path as production:
  DaprCredentialVault
    ├── objectstore GET  →  bindings.localstorage (temp dir)
    └── GetSecret        →  secretstores.local.file (temp JSON file, multiValued)

``ATLAN_DEPLOYMENT_NAME=ci`` (set before SDK imports) tells the SDK to use the
full Dapr API for both legs, bypassing the LOCAL_ENVIRONMENT short-circuit in
``_get_secret()`` that would otherwise read the secrets file directly.

``mysql_database`` and ``mysql_executor`` are aliases so the test files keep
their existing fixture names.

Run tests with: uv run pytest tests/integration/ -v
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("ATLAN_APPLICATION_NAME", "mysql")
os.environ.setdefault("ATLAN_DEPLOYMENT_NAME", "ci")

import docker  # noqa: E402
import pymysql  # noqa: E402
import pymysql.constants.CLIENT  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from application_sdk.dev import embedded_dapr  # noqa: E402
from application_sdk.observability.logger_adaptor import get_logger  # noqa: E402
from application_sdk.testing.integration.fixtures import *  # noqa: E402, F403
from testcontainers.mysql import MySqlContainer  # noqa: E402

from app.mysql import MySQLApp  # noqa: E402

_TEST_CREDENTIAL_GUID = "test-mysql-cred"

PROJECT_ROOT = Path(__file__).parent.parent.parent
SEED_SQL = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "seed.sql"

logger = get_logger("integration")

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


@pytest.fixture(scope="session")
def integration_app_cls() -> type[MySQLApp]:
    return MySQLApp


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


@pytest.fixture(scope="session")
def integration_source():
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


@pytest.fixture(scope="session")
def mysql_database(integration_source):
    """Alias preserving the fixture name the test files request."""
    return integration_source


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
    integration_source,
    dapr_secrets_file: Path,
    dapr_objectstore_dir: Path,
) -> str:
    """Write MySQL credential files for DaprCredentialVault resolution.

    The ``integration_source`` dependency orders this after the database is up,
    so MYSQL_HOST/PORT/USER/PASSWORD are set. Replicates what
    ``POST /workflows/v1/dev/local-vault`` does, directly:

    Objectstore (non-sensitive: host, port, authType) →
        ``{dapr_objectstore_dir}/persistent-artifacts/apps/mysql/
          credentials/{guid}/config.json``
        served by Dapr's bindings.localstorage on GET.

    Secrets file (sensitive: username, password) →
        ``{dapr_secrets_file}`` as ``{"<guid>": {"username": ..., "password": ...}}``
        served by Dapr's secretstores.local.file on GetSecret("<guid>").
    """
    del integration_source
    guid = _TEST_CREDENTIAL_GUID

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

    secrets = {
        guid: {
            "username": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", ""),
        }
    }
    dapr_secrets_file.write_text(json.dumps(secrets, indent=2))

    return guid


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def infrastructure(
    store_root: Path,
    integration_secrets: Mapping[str, str],
    mysql_credentials_files: str,
    dapr_secrets_file: Path,
    dapr_objectstore_dir: Path,
):
    """Kit infrastructure wrapped in a live daprd sidecar.

    Replaces the kit's ``infrastructure`` (star-imported fixtures replace, they
    do not wrap) but reuses its body through ``kit_infrastructure`` so the
    mocked state/secret stores, the session LocalStore, and the observability
    deployment-store swap+restore all behave exactly as the kit's own.

    The daprd leg exists because this suite exercises production
    ``DaprCredentialVault`` resolution for ``credential_guid`` inputs, which
    the kit's ``MockSecretStore`` cannot serve. Writes component YAMLs —
    secretstores.local.file in multiValued=true mode (so the vault can call
    GetSecret(guid) through the full Dapr API, which the SDK's default
    embedded_dapr components don't cover) plus a localstorage objectstore —
    then hands them to the SDK's public ``embedded_dapr(components_dir=...)``
    seam. embedded_dapr owns the daprd lifecycle: cached-binary download,
    free-port allocation, DAPR_HTTP_PORT/DAPR_GRPC_PORT/DAPR_COMPONENTS_PATH
    save+restore, readiness wait, and teardown. The ``mysql_credentials_files``
    dependency orders the credential files before daprd starts.

    Async because ``embedded_dapr`` is an async contextmanager; the kit's
    fixtures module documents an async daprd lifecycle as out of scope for the
    shipped ``infrastructure`` and names this suite as the reference shape.
    """
    del mysql_credentials_files
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

    try:
        async with embedded_dapr(
            app_id="mysql",
            components_dir=str(components_dir),
            log_level="error",
        ):
            logger.info("Embedded daprd ready via SDK embedded_dapr")
            with kit_infrastructure(store_root, integration_secrets) as ctx:  # noqa: F405
                yield ctx
    finally:
        shutil.rmtree(components_dir, ignore_errors=True)
        shutil.rmtree(eventstore_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def mysql_executor(executor):  # noqa: F405
    """Alias preserving the fixture name the test files request."""
    return executor
