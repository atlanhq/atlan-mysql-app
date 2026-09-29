"""The files in api/api-files.txt can ship as atlan_mysql_api unchanged.

The consolidated API host installs them as ``atlan_mysql_api.*``; the worker
imports the same files as ``app.*``. That works only while every import
between them is relative and stays inside the list. An absolute ``from app...``
import would work in the worker and then fail on the host, because the host
has no ``app`` package. (CI's api-member job builds the wheel, installs it
alone, and serves it as the host does.)
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _listed() -> list[str]:
    lines = (REPO_ROOT / "api" / "api-files.txt").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def test_every_listed_file_exists() -> None:
    for rel in _listed():
        assert (REPO_ROOT / rel).is_file(), rel


def test_listed_modules_import_each_other_relatively_and_only_each_other() -> None:
    listed = {Path(rel).stem for rel in _listed() if rel.endswith(".py")}
    for rel in _listed():
        if not rel.endswith(".py"):
            continue
        tree = ast.parse((REPO_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                target = (node.module or "").split(".")[0]
                assert target in listed, f"{rel}: relative import of unlisted {target}"
            elif (
                isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] == "app"
            ):
                raise AssertionError(f"{rel}: absolute import from app ({node.module})")
            elif isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "app" for a in node.names), rel


def test_the_worker_and_the_package_name_the_same_handler_source() -> None:
    from app.handler import MySQLAppHandler  # noqa: PLC0415 — the worker's import

    assert (
        Path(__import__("inspect").getfile(MySQLAppHandler))
        == REPO_ROOT / "app" / "handler.py"
    )
