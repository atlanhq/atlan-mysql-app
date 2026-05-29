"""E2E test fixtures — MySQL via testcontainers + Dapr credential setup.

When MYSQL_HOST is already set (local dev / remote RDS), uses that.
Otherwise spins up a MySQL container with seed data via testcontainers.

Usage:
  Local dev (own MySQL):  source .env && make test-e2e
  CI (testcontainers):    make test-e2e   # no env vars needed, Docker required
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import docker
import pymysql
import pymysql.constants.CLIENT
import pytest
from testcontainers.mysql import MySqlContainer

PROJECT_ROOT = Path(__file__).parent.parent.parent
SEED_SQL = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "seed.sql"

logger = logging.getLogger("e2e")


def _mysql_host_preconfigured() -> bool:
    """Check if MySQL connection is already configured via env vars."""
    return bool(os.environ.get("MYSQL_HOST"))


def _docker_available() -> bool:
    """Check if Docker daemon is reachable."""
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def mysql_database():
    """Provide a MySQL database for e2e tests.

    Priority:
    1. MYSQL_HOST env var set → use external database
    2. Docker available → start MySQL via testcontainers with seed data
    3. Neither → skip, tests will use whatever defaults the app has
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

        # Seed the database (needs root to create databases)
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

        # Log what was created
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


@pytest.fixture(scope="session", autouse=True)
def setup_dapr_credentials(mysql_database):
    """Provision MySQL credentials via the SDK's /dev/local-vault endpoint.

    Using the SDK endpoint rather than writing files directly ensures the
    correct objectstore path (which embeds ATLAN_APPLICATION_NAME) is used
    regardless of whether the app runs in embedded-Dapr or external-Dapr mode.
    The endpoint splits sensitive fields (username/password) into the local
    secrets file and non-sensitive fields (host/port/authType) into the Dapr
    objectstore at the app-name-scoped path the credential vault expects.

    The returned GUID is stored in CREDENTIAL_GUID so the test helpers
    (``_credential_guid()``) pick it up automatically.
    """
    import requests as _req

    app_url = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    username = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = os.environ.get("MYSQL_PORT", "3306")

    resp = _req.post(
        f"{app_url}/workflows/v1/dev/local-vault",
        json={
            "username": username,
            "password": password,
            "host": host,
            "port": port,
            "authType": "basic",
            "type": "all",
        },
        timeout=15,
    )
    resp.raise_for_status()
    guid = resp.json()["data"]["credential_guid"]

    prev = os.environ.get("CREDENTIAL_GUID")
    os.environ["CREDENTIAL_GUID"] = guid

    yield

    if prev is None:
        os.environ.pop("CREDENTIAL_GUID", None)
    else:
        os.environ["CREDENTIAL_GUID"] = prev
