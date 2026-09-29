"""Package the app/ files listed in ``api-files.txt`` as ``atlan_mysql_api``.

The handler, client and failure classes live once, in ``app/``, and are edited
there. The worker imports them as ``app.*``. This wheel ships the same files as
``atlan_mysql_api.*`` for the consolidated API host, which installs it on
atlan-application-sdk-api alone. Imports between the listed files are
relative, so each file works under either name.

The sdist keeps the files at ``app/...`` next to this file; a wheel built from
the unpacked sdist reads them there, and a wheel built in the repo reads them
from the repo root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

LIST = "api-files.txt"
SOURCE = "app/"
PACKAGE = "atlan_mysql_api/"


def listed_files(root: Path) -> list[str]:
    lines = (root / LIST).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


class AppFilesHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        here = Path(self.root).resolve()
        repo = here.parent
        for rel in listed_files(here):
            source = here / rel if (here / rel).is_file() else repo / rel
            target = (
                rel
                if self.target_name == "sdist"
                else PACKAGE + rel.removeprefix(SOURCE)
            )
            build_data["force_include"][str(source)] = target
