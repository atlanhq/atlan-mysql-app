"""Integration conftest: the SDK's shared fixture kit, mysql-specific source only.

Everything the kit owns — embedded Temporal, client, in-process worker,
executor shim, task-queue derivation, mocked infrastructure, artifact
preservation — comes from the star-import of
``application_sdk.testing.integration.fixtures``. This file keeps only what is
genuinely mysql's:

* ``integration_source`` — a seeded MySQL testcontainer, with the MYSQL_HOST
  escape hatch (external database) and the no-Docker skip path preserved.
* ``integration_secrets`` — seeds the kit's ``MockSecretStore`` with the
  container's connection credential under a named key. Workflow inputs route
  by ``credential_ref`` (named path), which ``CredentialResolver`` serves from
  the injected secret store — no daprd sidecar needed. The secret value is the
  full raw credential JSON (host/port/authType plus username/password), the
  same merged shape ``DaprCredentialVault`` produces in production, handed
  verbatim to ``BaseSQLClient.load()``.

``mysql_database`` and ``mysql_executor`` are aliases so the test files keep
their existing fixture names.

Run tests with: uv run pytest tests/integration/ -v
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("ATLAN_APPLICATION_NAME", "mysql")
os.environ.setdefault("ATLAN_DEPLOYMENT_NAME", "ci")

import docker  # noqa: E402
import pymysql  # noqa: E402
import pymysql.constants.CLIENT  # noqa: E402
import pytest  # noqa: E402
from application_sdk.credentials.ref import CredentialRef, basic_ref  # noqa: E402
from application_sdk.observability.logger_adaptor import get_logger  # noqa: E402
from application_sdk.testing.integration.fixtures import *  # noqa: E402, F403
from testcontainers.mysql import MySqlContainer  # noqa: E402

from app.mysql import MySQLApp  # noqa: E402

_TEST_CREDENTIAL_NAME = "test-mysql-cred"

PROJECT_ROOT = Path(__file__).parent.parent.parent
SEED_SQL = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "seed.sql"

logger = get_logger("integration")


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
def integration_secrets(integration_source) -> Mapping[str, str]:
    """Seed the kit's MockSecretStore with the live database's credential.

    The ``integration_source`` dependency orders this after the database is up,
    so MYSQL_HOST/PORT/USER/PASSWORD are set. The value is the raw credential
    JSON that ``CredentialResolver.resolve_raw`` returns for the named ref and
    ``SqlApp._init_sql_client`` passes to ``BaseSQLClient.load()``.
    """
    del integration_source
    return {
        _TEST_CREDENTIAL_NAME: json.dumps({
            "host": os.environ.get("MYSQL_HOST", "localhost"),
            "port": os.environ.get("MYSQL_PORT", "3306"),
            "authType": "basic",
            "credentialSource": "direct",
            "username": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", ""),
        })
    }


@pytest.fixture(scope="session")
def mysql_credential_ref() -> CredentialRef:
    """Named ref matching the ``integration_secrets`` seed."""
    return basic_ref(_TEST_CREDENTIAL_NAME)


@pytest.fixture(scope="session")
def mysql_executor(executor):  # noqa: F405
    """Alias preserving the fixture name the test files request."""
    return executor
