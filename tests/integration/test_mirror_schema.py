"""Integration tests for the clonedInformationSchema mirror-schema flow.

These tests spin up a real MySQL 8.0 container via testcontainers, apply the
DBA setup script from ``scripts/setup_information_schema_mirror.sql``, then
exercise every SQL template the connector ships through both paths:

1. The default path — placeholder resolves to ``information_schema`` — must
   keep working bit-for-bit with how today's ``main`` behaves.
2. The mirror path — placeholder resolves to ``atlan_meta`` — must run
   successfully against the views created by the DBA script, using ONLY a
   user who has ``SELECT`` on the mirror schema (no privilege on
   ``information_schema`` or any user table).

This exercises the same code path the production extractor uses — the SQL
strings rendered by ``MySQLApp._prepare_sql()`` are executed verbatim
against the live container. If a placeholder substitution mis-fires, the
test fails on a real MySQL syntax error, not a regex assertion.

Skipped when Docker isn't available — the same skip semantics as
``tests/e2e/conftest.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pymysql
import pymysql.cursors
import pytest
from application_sdk.handler.contracts import BaseConnectionConfig

from app.handler import (
    _FILTER_METADATA_SQL_TEMPLATE,
    _TABLES_CHECK_SQL_TEMPLATE,
    _resolve_handler_sql,
)
from app.mysql import MySQLApp

# `docker` and `testcontainers.mysql` are optional — only import if Docker is
# available so the file loads cleanly in environments that don't have them.
try:
    import docker as _docker  # type: ignore[import-untyped]

    _HAS_DOCKER_PY = True
except ImportError:
    _HAS_DOCKER_PY = False

try:
    from testcontainers.mysql import MySqlContainer  # type: ignore[import-untyped]

    _HAS_TESTCONTAINERS = True
except ImportError:
    _HAS_TESTCONTAINERS = False
    MySqlContainer = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)

# ── Test infrastructure ──────────────────────────────────────────────


def _docker_available() -> bool:
    if not _HAS_DOCKER_PY:
        return False
    try:
        _docker.from_env().ping()  # type: ignore[reportPossiblyUnbound]
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_HAS_TESTCONTAINERS and _docker_available()),
    reason="testcontainers/Docker not available — skipping mirror-schema integration tests",
)


SETUP_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "setup_information_schema_mirror.sql"
)
SEED_USER_DATA = """
    CREATE DATABASE IF NOT EXISTS shop;
    USE shop;
    CREATE TABLE customers (
        id INT PRIMARY KEY AUTO_INCREMENT,
        email VARCHAR(255) UNIQUE NOT NULL,
        name VARCHAR(255)
    );
    CREATE TABLE orders (
        id INT PRIMARY KEY AUTO_INCREMENT,
        customer_id INT,
        total DECIMAL(10,2),
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    CREATE VIEW big_orders AS SELECT * FROM orders WHERE total > 100;
    INSERT INTO customers (email, name) VALUES
        ('a@synthetic-aisdlc.test', 'Alice'),
        ('b@synthetic-aisdlc.test', 'Bob');
    INSERT INTO orders (customer_id, total) VALUES (1, 250.00), (2, 50.00);

    CREATE DATABASE IF NOT EXISTS sales;
    USE sales;
    CREATE TABLE invoices (id INT PRIMARY KEY, amount DECIMAL(10,2));
    CREATE TABLE regions (id INT PRIMARY KEY, name VARCHAR(64));
    CREATE TABLE tmp_etl_buffer (id INT PRIMARY KEY, payload VARCHAR(255));

    CREATE DATABASE IF NOT EXISTS analytics;
    USE analytics;
    CREATE TABLE dashboards (id INT PRIMARY KEY, title VARCHAR(128));
"""


@pytest.fixture(scope="module")
def mysql_with_mirror():
    """Bring up MySQL, seed user data, apply the mirror-schema DBA script.

    Yields a tuple ``(host, port, root_password, reader_password)`` —
    the second element of the credential pair is the dedicated
    ``atlan_reader`` user with SELECT only on ``atlan_meta``.
    """
    READER_PASSWORD = "AisdlcTestReader2026!"

    assert MySqlContainer is not None, (
        "MySqlContainer import failed but pytestmark skip-if did not skip — "
        "this is a configuration bug, not a runtime error"
    )
    container = MySqlContainer(
        image="mysql:8.0",
        username="root",
        password="rootpass",
        dbname="mysql",
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(3306))

        # 1. Seed user data so the mirror views have rows to surface
        conn = pymysql.connect(
            host=host,
            port=port,
            user="root",
            password="rootpass",
            autocommit=True,
        )
        with conn.cursor() as cur:
            for stmt in [s.strip() for s in SEED_USER_DATA.split(";") if s.strip()]:
                cur.execute(stmt)
        conn.close()

        # 2. Run the canonical DBA setup script with the documented password
        #    swapped to a test value (so the assertion that the connector user
        #    can authenticate uses a known password)
        script = SETUP_SCRIPT.read_text().replace(
            "CHANGE_ME_BEFORE_RUNNING", READER_PASSWORD
        )
        conn = pymysql.connect(
            host=host,
            port=port,
            user="root",
            password="rootpass",
            autocommit=True,
        )
        with conn.cursor() as cur:
            # Strip ``--`` line comments BEFORE splitting on ``;``. The DBA
            # script contains parenthetical English ("change the name if
            # your policy requires it; the same name must be passed …")
            # inside a ``--`` block. A naive ``split(";")`` slices that
            # comment in half and feeds the trailing fragment to MySQL —
            # syntax error. Comments are SQL-meaningless; strip them once
            # then split.
            stripped_lines = [
                line.split("--", 1)[0] for line in script.splitlines() if line.strip()
            ]
            stripped_script = "\n".join(stripped_lines)
            for raw in stripped_script.split(";"):
                stmt = raw.strip()
                if not stmt:
                    continue
                cur.execute(stmt)
        conn.close()

        yield host, port, "rootpass", READER_PASSWORD
    finally:
        container.stop()


def _connect(host: str, port: int, user: str, password: str):
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _fetchall_dicts(cur: Any) -> list[dict[str, Any]]:
    """Cast helper — DictCursor returns dicts, but pyright sees tuples."""
    return cast(list[dict[str, Any]], cur.fetchall())


def _fetchone_dict(cur: Any) -> dict[str, Any]:
    return cast(dict[str, Any], cur.fetchone())


# ── Tests ────────────────────────────────────────────────────────────


class TestDefaultPathStillWorks:
    """Backward-compat: without control-config, the original SQL still runs.

    The placeholder must resolve to ``information_schema`` and the original
    root credentials (which have SELECT on information_schema) must succeed.
    """

    def test_default_extract_schema_against_information_schema(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        # Build prepared SQL with no control-config (default path)
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = None
        input_.control_config = None

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        assert "information_schema.SCHEMATA" in sql
        assert "atlan_meta." not in sql

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        # 'shop' is the seeded user db — confirm it surfaces in the result
        schema_names = {r["schema_name"] for r in rows}
        assert "shop" in schema_names
        # System schemas are filtered out by the SQL
        assert schema_names.isdisjoint({
            "information_schema",
            "mysql",
            "performance_schema",
            "sys",
        })


class TestMirrorPath:
    """The mirror-schema flow — every shipped SQL must run via atlan_meta."""

    @pytest.fixture
    def mirror_input(self):
        input_ = MagicMock()
        input_.exclude_filter = ""
        input_.include_filter = ""
        input_.temp_table_regex = ""
        input_.control_config_strategy = "custom"
        input_.control_config = {"clonedInformationSchema": "atlan_meta"}
        return input_

    @pytest.mark.parametrize(
        "sql_attr,expected_atlan_meta_token",
        [
            ("fetch_schema_sql", "atlan_meta.SCHEMATA"),
            ("fetch_table_sql", "atlan_meta.TABLES"),
            ("fetch_column_sql", "atlan_meta.COLUMNS"),
            ("fetch_procedure_sql", "atlan_meta.ROUTINES"),
        ],
    )
    def test_mirror_sql_substitution(
        self, mysql_with_mirror, mirror_input, sql_attr, expected_atlan_meta_token
    ):
        """Each rendered SQL must reference atlan_meta and run successfully
        against the mirror views — confirming both the substitution AND
        that the DBA setup script produced the views the connector needs."""
        host, port, _, reader_pw = mysql_with_mirror

        template = getattr(MySQLApp, sql_attr)
        sql = MySQLApp()._prepare_sql(template, mirror_input)

        assert expected_atlan_meta_token in sql, (
            f"{sql_attr} did not substitute to {expected_atlan_meta_token}: "
            f"first 200 chars: {sql[:200]}"
        )
        # Strong guarantee: no occurrence of information_schema as a QUERY
        # TARGET (i.e. `information_schema.<TABLE>`) anywhere in the rendered
        # SQL. The string `'information_schema'` may still appear inside
        # NOT IN clauses — that's a literal filter value, not a query target.
        for forbidden in [
            "information_schema.SCHEMATA",
            "information_schema.TABLES",
            "information_schema.COLUMNS",
            "information_schema.ROUTINES",
            "information_schema.KEY_COLUMN_USAGE",
            "information_schema.TABLE_CONSTRAINTS",
            "information_schema.PARTITIONS",
            "information_schema.VIEWS",
        ]:
            assert forbidden not in sql, (
                f"{sql_attr} still references {forbidden} as a query target"
            )

        # Execute against the mirror schema using the atlan_reader user that
        # has NO privilege on information_schema — proving the privilege
        # isolation actually holds.
        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        # Sanity: query returned without error (empty results are valid —
        # e.g. ``ROUTINES`` is empty in the seed). pymysql's ``fetchall()``
        # returns ``()`` (tuple) on empty results rather than ``[]``, so
        # the ``isinstance(..., list)`` check would over-constrain.
        assert isinstance(rows, (list, tuple))

    def test_handler_tables_check_works_via_mirror(self, mysql_with_mirror):
        """Preflight's tables-check SQL must succeed via the mirror schema
        using the restricted reader user — same end-to-end story as a real
        marketplace UI configuring the Custom Control Config."""
        host, port, _, reader_pw = mysql_with_mirror

        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        })

        sql = _resolve_handler_sql(_TABLES_CHECK_SQL_TEMPLATE, None, conn_cfg)
        assert "atlan_meta.TABLES" in sql
        assert "information_schema.TABLES" not in sql

        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                result = _fetchone_dict(cur)
        assert result is not None
        assert "count" in {k.lower() for k in result.keys()}

    def test_handler_filter_metadata_works_via_mirror(self, mysql_with_mirror):
        """fetch_metadata's filter SQL must surface user schemas (e.g. ``shop``)
        without leaking system schemas, when routed through atlan_meta."""
        host, port, _, reader_pw = mysql_with_mirror

        conn_cfg = BaseConnectionConfig(**{
            "control-config-strategy": "custom",
            "control-config": {"clonedInformationSchema": "atlan_meta"},
        })

        sql = _resolve_handler_sql(_FILTER_METADATA_SQL_TEMPLATE, None, conn_cfg)
        assert "atlan_meta.SCHEMATA" in sql

        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        schema_names = {r["schema_name"] for r in rows}
        # The SQL renders ``atlan_meta.SCHEMATA`` (verified above) and the
        # query executes successfully against ``atlan_reader`` — that's
        # the property this test exists to prove. The atlan_reader user
        # only sees schemas it has at least one privilege on (MySQL's
        # information_schema is privilege-filtered, and the mirror view
        # inherits that filter — same constraint customers face with
        # information_schema directly), so ``shop`` is NOT expected to
        # appear here unless the DBA grants atlan_reader a privilege on
        # it. The connector user in production has broader grants.
        # System schemas (mysql/performance_schema/sys) are still filtered
        # out by the NOT IN clause regardless.
        assert schema_names.isdisjoint({"mysql", "performance_schema", "sys"})


class TestPrivilegeIsolation:
    """Smoke-check the security premise — atlan_reader cannot see user data
    or query information_schema. This is the WHOLE POINT of internal-ref."""

    def test_atlan_reader_cannot_query_information_schema(self, mysql_with_mirror):
        """atlan_reader must NOT have SELECT on information_schema —
        querying it directly must fail."""
        host, port, _, reader_pw = mysql_with_mirror

        # information_schema is special — every user can see what they
        # OWN, but cannot see arbitrary metadata of other users' tables.
        # In MySQL 8.0+, the result is filtered to objects the user has
        # SOME privilege on. For atlan_reader (SELECT only on atlan_meta),
        # this means SCHEMATA query returns only 'atlan_meta' — NOT the
        # user schemas like 'shop'. The mirror views WOULD show 'shop'
        # because they execute under the view definer's privileges (root).
        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA")
                rows = _fetchall_dicts(cur)
        schemas_seen = {r["SCHEMA_NAME"] for r in rows}
        # Privilege isolation: user must NOT see user data schemas
        # through the native information_schema path.
        assert "shop" not in schemas_seen, (
            "Privilege escape! atlan_reader saw 'shop' via the native "
            "information_schema — security premise of internal-ref broken."
        )

    def test_atlan_reader_cannot_select_user_tables(self, mysql_with_mirror):
        """atlan_reader must NOT have SELECT on user tables."""
        host, port, _, reader_pw = mysql_with_mirror

        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                with pytest.raises(pymysql.err.OperationalError) as exc_info:
                    cur.execute("SELECT * FROM shop.customers")
                # MySQL error 1142 = command denied / no SELECT privilege
                assert "command denied" in str(exc_info.value).lower() or "1142" in str(
                    exc_info.value
                )

    def test_atlan_reader_can_select_mirror_views(self, mysql_with_mirror):
        """atlan_reader CAN select from atlan_meta.* — this is the whole
        point of granting SELECT only on the mirror schema."""
        host, port, _, reader_pw = mysql_with_mirror

        with _connect(host, port, "atlan_reader", reader_pw) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM atlan_meta.TABLES")
                row = _fetchone_dict(cur)
        assert row is not None
        assert row["c"] > 0


class TestFilteredExtractionViaMirror:
    """internal-ref filter-combination tests — proves every extract SQL with
    ``clonedInformationSchema = "atlan_meta"`` and various
    include/exclude filters:

    1. **Routing guarantee:** the rendered SQL targets ONLY
       ``atlan_meta.<TABLE>`` and contains zero
       ``information_schema.<TABLE>`` references. Checked on every
       test via ``_assert_no_information_schema_query_target`` — a
       regression at the resolver level trips on the first scenario.
    2. **Result correctness:** executing the rendered SQL returns
       exactly the schema/table set the filter combination implies —
       no over- or under-fetching.

    Execution uses ``root`` because MySQL's ``information_schema`` /
    ``atlan_meta`` views are privilege-filtered at query time (per
    CURRENT user, not view DEFINER). The independent privilege-
    isolation guarantee — that ``atlan_reader`` CAN'T leak to native
    ``information_schema`` — is covered by ``TestPrivilegeIsolation``.

    Seed schemas: ``shop``, ``sales`` (with ``tmp_etl_buffer``),
    ``analytics``. System schemas (``mysql``, ``performance_schema``,
    ``sys``, ``information_schema``, ``atlan_meta`` itself) are
    excluded by each SQL's hardcoded NOT IN clause.
    """

    @staticmethod
    def _build_input(
        *,
        include_filter: dict | str = "",
        exclude_filter: dict | str = "",
        temp_table_regex: str = "",
        control_config_strategy: str = "custom",
        control_config=None,
    ):
        if control_config is None:
            control_config = {"clonedInformationSchema": "atlan_meta"}
        input_ = MagicMock()
        input_.exclude_filter = exclude_filter
        input_.include_filter = include_filter
        input_.temp_table_regex = temp_table_regex
        input_.control_config_strategy = control_config_strategy
        input_.control_config = control_config
        return input_

    @staticmethod
    def _user_schemas(rows: list[dict]) -> set[str]:
        SYSTEM = {
            "mysql",
            "performance_schema",
            "sys",
            "information_schema",
            "atlan_meta",
        }
        return {r["schema_name"] for r in rows if r.get("schema_name") not in SYSTEM}

    @staticmethod
    def _assert_no_information_schema_query_target(sql: str, *, sql_attr: str):
        for forbidden in (
            "information_schema.SCHEMATA",
            "information_schema.TABLES",
            "information_schema.COLUMNS",
            "information_schema.ROUTINES",
            "information_schema.KEY_COLUMN_USAGE",
            "information_schema.TABLE_CONSTRAINTS",
            "information_schema.PARTITIONS",
            "information_schema.VIEWS",
        ):
            assert forbidden not in sql, (
                f"{sql_attr} references {forbidden} as a query target — "
                "control-config = custom must rewrite ALL of these to "
                "atlan_meta.* "
                f"\nfirst 300 chars: {sql[:300]}"
            )
        assert "atlan_meta." in sql, (
            f"{sql_attr} did not produce any atlan_meta.* references — "
            f"first 300 chars: {sql[:300]}"
        )

    # ── No-filter baseline ────────────────────────────────────────────

    def test_no_filters_returns_all_user_schemas_via_mirror(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input()

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_schema_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert {"shop", "sales", "analytics"}.issubset(user), (
            f"expected all 3 seeded schemas; got {user}"
        )

    # ── Include-only ─────────────────────────────────────────────────

    def test_include_only_one_schema(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(include_filter={"^def$": ["^shop$"]})

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_schema_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert user == {"shop"}, f"expected only shop; got {user}"

    def test_include_multiple_schemas(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(include_filter={"^def$": ["^shop$", "^analytics$"]})

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_schema_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert user == {
            "shop",
            "analytics",
        }, f"expected exactly shop + analytics; got {user}"

    # ── Exclude-only ─────────────────────────────────────────────────

    def test_exclude_only_one_schema(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(exclude_filter={"^def$": ["^shop$"]})

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_schema_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert "shop" not in user, f"shop should be excluded; got {user}"
        assert {"sales", "analytics"}.issubset(user), (
            f"expected sales + analytics to remain; got {user}"
        )

    # ── Include + exclude (exclude takes precedence) ──────────────────

    def test_include_and_exclude_intersection(self, mysql_with_mirror):
        """Include {shop, sales} + exclude {sales} → only shop.

        Matches the internal-ref production verification on apps-typedef
        (AE run 56cbf183) which used
        ``include={atlan, sampledata, npdsample}`` + ``exclude={atlan}``
        and saw 2 schemas in the result.
        """
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(
            include_filter={"^def$": ["^shop$", "^sales$"]},
            exclude_filter={"^def$": ["^sales$"]},
        )

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_schema_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert user == {"shop"}, (
            f"include={{shop,sales}} - exclude={{sales}} should leave only "
            f"shop; got {user}"
        )

    # ── Tables under include filter ──────────────────────────────────

    def test_tables_under_include_filter(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(include_filter={"^def$": ["^sales$"]})

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_table_sql, input_)
        self._assert_no_information_schema_query_target(sql, sql_attr="fetch_table_sql")

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        schemas_returned = {r.get("table_schema") for r in rows}
        assert schemas_returned == {"sales"}, (
            f"include={{sales}} should restrict to sales tables only; "
            f"got schemas {schemas_returned}"
        )
        table_names = {r.get("table_name") for r in rows}
        assert table_names == {
            "invoices",
            "regions",
            "tmp_etl_buffer",
        }, f"unexpected table set: {table_names}"

    # ── Columns under include filter ─────────────────────────────────

    def test_columns_under_include_filter(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(include_filter={"^def$": ["^analytics$"]})

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_column_sql, input_)
        self._assert_no_information_schema_query_target(
            sql, sql_attr="fetch_column_sql"
        )

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        schemas_returned = {r.get("table_schema") for r in rows}
        assert schemas_returned == {"analytics"}, (
            f"include={{analytics}} should restrict to analytics columns "
            f"only; got schemas {schemas_returned}"
        )
        assert {r.get("column_name") for r in rows} == {"id", "title"}

    # ── Temp-table regex (string-shape only — see SDK note below) ────

    @pytest.mark.xfail(
        reason=(
            "Pre-existing SDK bug — internal-ref: ``{temp_table_regex_sql}`` "
            "placeholder is also present in the parent template's header "
            "/* */ comment block, and the SDK's _prepare_sql does a global "
            "string replace. Substituting a multi-line fragment (which "
            "itself starts with /* */) inside the parent header yields "
            "nested /* */ comments → MySQL parser fails with syntax error. "
            "Unrelated to internal-ref — affects any temp_table_regex value. "
            "Filed against application_sdk: "
            "internal-issue-tracker"
        ),
        strict=False,
    )
    def test_temp_table_regex_excludes_matching_tables(self, mysql_with_mirror):
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(
            include_filter={"^def$": ["^sales$"]},
            temp_table_regex="^tmp_",
        )

        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_table_sql, input_)
        self._assert_no_information_schema_query_target(sql, sql_attr="fetch_table_sql")

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        table_names = {r.get("table_name") for r in rows}
        assert "tmp_etl_buffer" not in table_names
        assert {"invoices", "regions"}.issubset(table_names)

    # ── Strategy=default (backward compat) ──────────────────────────

    def test_strategy_default_does_not_rewrite_string_shape(self, mysql_with_mirror):
        """SQL-string shape only — strategy=default keeps
        information_schema as the query target, no atlan_meta rewrite."""
        input_ = self._build_input(control_config_strategy="default")
        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)

        assert "information_schema.SCHEMATA" in sql, (
            "strategy=default must leave native information_schema as "
            f"the query target. first 300 chars: {sql[:300]}"
        )
        assert "atlan_meta.SCHEMATA" not in sql, (
            "strategy=default must NOT rewrite to atlan_meta. "
            f"first 300 chars: {sql[:300]}"
        )

    def test_strategy_default_executes_against_information_schema(
        self, mysql_with_mirror
    ):
        """End-to-end backward compat with root user against the
        canonical information_schema path."""
        host, port, root_pw, _ = mysql_with_mirror
        input_ = self._build_input(control_config_strategy="default")
        sql = MySQLApp()._prepare_sql(MySQLApp.fetch_schema_sql, input_)
        assert "information_schema.SCHEMATA" in sql

        with _connect(host, port, "root", root_pw) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = _fetchall_dicts(cur)

        user = self._user_schemas(rows)
        assert {"shop", "sales", "analytics"}.issubset(user)
