"""Scheduled mutation-testing report + survivor work-list upsert.

Runs after a full `mutmut run`: parses `mutmut results --all true` into a
per-module scorecard, writes it to $GITHUB_STEP_SUMMARY, and keeps exactly
one open GitHub issue (label: mutation-testing) holding the current
survivor work-list:

- survivors found and no open issue  -> create it
- survivors found and issue exists   -> replace its body with the fresh list
- zero survivors                     -> close the issue (goal state)

Each surviving mutant is a seeded bug the unit suite does not catch;
killing it means adding a test that fails on the mutated code. Inspect one
locally with `uv run --group mutation mutmut show <mutant-name>`.

Stdlib-only; branching lives here so the workflow run block stays
straight-line. Always exits 0 — the scheduled lane is advisory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

DETECTED = frozenset({"killed", "timeout", "caught by type check", "segfault"})
ISSUE_LABEL = "mutation-testing"
ISSUE_TITLE = "Mutation testing: surviving mutants work-list"


def mutmut_results() -> str:
    return subprocess.run(
        [
            "uv",
            "run",
            "--all-extras",
            "--all-groups",
            "mutmut",
            "results",
            "--all",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def parse(results_output: str) -> tuple[dict[str, Counter], list[str]]:
    """Per-module status counts + the flat list of surviving mutant names."""
    by_module: dict[str, Counter] = defaultdict(Counter)
    survivors: list[str] = []
    for line in results_output.splitlines():
        line = line.strip()
        if not line or ": " not in line:
            continue
        name, status = line.rsplit(": ", 1)
        module = ".".join(p for p in name.split(".") if not p.startswith("x"))
        by_module[module][status] += 1
        if status == "survived":
            survivors.append(name)
    return by_module, sorted(survivors)


def scorecard(by_module: dict[str, Counter]) -> str:
    lines = [
        "## Mutation testing — weekly full run",
        "",
        "| module | killed | survived | no-tests | score |",
        "|---|---|---|---|---|",
    ]
    total: Counter = Counter()
    for module, counts in sorted(by_module.items()):
        detected = sum(counts[s] for s in DETECTED)
        survived = counts["survived"]
        decided = detected + survived
        score = f"{detected / decided:.0%}" if decided else "n/a"
        lines.append(
            f"| {module} | {detected} | {survived} | {counts['no tests']} | {score} |"
        )
        total.update(counts)
    detected = sum(total[s] for s in DETECTED)
    survived = total["survived"]
    decided = detected + survived
    score = f"{detected / decided:.0%}" if decided else "n/a"
    lines.append(
        f"| **TOTAL** | **{detected}** | **{survived}** | "
        f"**{total['no tests']}** | **{score}** |"
    )
    return "\n".join(lines) + "\n"


def issue_body(survivors: list[str], card: str) -> str:
    items = "\n".join(f"- [ ] `{name}`" for name in survivors)
    return (
        f"{card}\n"
        "## Survivors — seeded bugs the unit suite does not catch\n\n"
        "Each unchecked item needs a test that fails on the mutated code. "
        "Inspect the exact code change with "
        "`uv run --group mutation mutmut show <mutant-name>`; equivalent "
        "mutants (no observable behaviour difference) should be noted and "
        "checked off with a comment instead.\n\n"
        f"{items}\n\n"
        "_Maintained automatically by the scheduled mutation-tests workflow; "
        "the body is replaced on every run._\n"
    )


def find_open_issue() -> int | None:
    out = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--label",
            ISSUE_LABEL,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    issues = json.loads(out or "[]")
    return issues[0]["number"] if issues else None


def upsert_issue(survivors: list[str], card: str) -> None:
    number = find_open_issue()
    if not survivors:
        if number is not None:
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "close",
                    str(number),
                    "--comment",
                    "Weekly mutation run found zero surviving mutants — work-list complete. 🎉",
                ],
                check=True,
            )
        return
    body = issue_body(survivors, card)
    if number is None:
        subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                ISSUE_TITLE,
                "--label",
                ISSUE_LABEL,
                "--body",
                body,
            ],
            check=True,
        )
    else:
        subprocess.run(
            ["gh", "issue", "edit", str(number), "--body", body],
            check=True,
        )


def main() -> int:
    by_module, survivors = parse(mutmut_results())
    card = scorecard(by_module)
    print(card)  # noqa: T201 — CLI output
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a") as fh:
            fh.write(card)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        upsert_issue(survivors, card)
    else:
        print(  # noqa: T201 — CLI output
            f"(local run — skipping issue upsert; {len(survivors)} survivors)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
