#!/usr/bin/env python3
"""Pre-commit hook: verify version.txt and CHANGELOG.md are updated when app code changes.

Checks staged files — if any app/ or pyproject.toml changes are staged,
ensures version.txt or CHANGELOG.md is also staged. Skips if only
tests/docs/CI files changed.
"""

import subprocess
import sys

APP_PATHS = ("app/", "pyproject.toml", "Dockerfile", "main.py", "Makefile", "atlan.yaml", ".github/workflows/")
SKIP_PATHS = ("tests/", ".github/", "docs/", "README.md", "CHANGELOG.md", "version.txt")


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    has_app_changes = any(any(f.startswith(p) for p in APP_PATHS) for f in staged)
    only_skip_paths = all(any(f.startswith(p) for p in SKIP_PATHS) for f in staged)

    if not has_app_changes or only_skip_paths:
        return 0

    has_version = "version.txt" in staged
    has_changelog = "CHANGELOG.md" in staged

    errors = []
    if not has_version:
        errors.append("version.txt not updated — bump the version for app changes")
    if not has_changelog:
        errors.append("CHANGELOG.md not updated — document your changes")

    if errors:
        print("Version/Changelog check failed:")
        for e in errors:
            print(f"  - {e}")
        print("\nStage version.txt and CHANGELOG.md, or use --no-verify to skip.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
