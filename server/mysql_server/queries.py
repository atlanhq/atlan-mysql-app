"""The SQL the serving surface runs, loaded from files that ship in the wheel.

Package-relative, never CWD-relative: the consolidated host's working directory
is the host's, and a path resolved against it silently points at nothing — the
read fails at import and the app is ejected with no useful message.

The three statements are the worker's own files, force-included into this wheel
so the two cannot drift. Placeholders are substituted here exactly as
``app/handler.py`` substitutes them, because the substituted text is what the
customer's database actually sees.
"""

from __future__ import annotations

from pathlib import Path

#: MySQL's placeholder when no database is selected (``DATABASE()`` is NULL).
DATABASE_PLACEHOLDER = "def"

_SQL_DIR = Path(__file__).resolve().parent / "sql"


def _read(name: str) -> str:
    return (_SQL_DIR / name).read_text().strip()


TEST_AUTH_SQL = _read("test_authentication.sql").replace(
    "{database_placeholder}", DATABASE_PLACEHOLDER
)

#: The advisory tables probe. The regex placeholders are neutralised rather than
#: left unbound: this check asks "can the role list tables at all", so filtering
#: to the customer's include/exclude set would make an empty result ambiguous.
TABLES_CHECK_SQL = (
    _read("tables_check.sql")
    .replace("{database_placeholder}", DATABASE_PLACEHOLDER)
    .replace("{normalized_exclude_regex}", "^$")
    .replace("{normalized_include_regex}", ".*")
    .replace("{temp_table_regex_sql}", "")
)

FILTER_METADATA_SQL = _read("filter_metadata.sql").replace(
    "{database_placeholder}", DATABASE_PLACEHOLDER
)

__all__ = [
    "DATABASE_PLACEHOLDER",
    "FILTER_METADATA_SQL",
    "TABLES_CHECK_SQL",
    "TEST_AUTH_SQL",
]
