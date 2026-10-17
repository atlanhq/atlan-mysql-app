"""The serving package must import without the worker package present.

The consolidated host installs ``atlan-mysql-server`` and nothing else — no
``app``. Any module here that reaches into the worker is a latent 500: it
imports fine in this repo, where the worker is right there on the path, and
fails the first time a route touches it on the host.

Runs in a subprocess with the worker blocked at the import hook, because the
worker IS importable in this repo and a same-process check would prove nothing.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap
import unittest

SERVER_ROOT = pathlib.Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent(
    '''
    import importlib, pathlib, sys

    BLOCKED = "app"

    class _NoWorker:
        """Stand in for the host, where the worker package is not installed."""

        def find_spec(self, fullname, path=None, target=None):
            if fullname == BLOCKED or fullname.startswith(BLOCKED + "."):
                raise ModuleNotFoundError(f"No module named {fullname!r}")
            return None

    sys.meta_path.insert(0, _NoWorker())

    root = pathlib.Path(sys.argv[1])
    failures = []
    for f in sorted((root / "mysql_server").rglob("*.py")):
        parts = list(f.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        mod = ".".join(parts)
        if not mod:
            continue
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            if BLOCKED in str(exc):
                failures.append(f"{mod}: {exc}")
        except Exception:
            # Config / optional-dependency problems are not the coupling this
            # test is about.
            pass

    print("\\n".join(failures))
    sys.exit(1 if failures else 0)
    '''
)


class TestServingPackageDoesNotNeedTheWorker(unittest.TestCase):
    def test_no_module_imports_the_worker(self):
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(SERVER_ROOT)],
            capture_output=True,
            text=True,
            cwd=str(SERVER_ROOT),
            timeout=600,
        )
        if proc.returncode != 0:
            listed = proc.stdout.strip() or proc.stderr.strip()
            self.fail(
                "these modules need the worker package, which the consolidated "
                "host does not install:\n" + listed
            )


if __name__ == "__main__":
    unittest.main()
