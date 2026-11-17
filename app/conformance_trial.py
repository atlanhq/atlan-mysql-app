"""TRIAL ONLY (FND-5029) - do not merge.

A deliberately planted blocking conformance violation (E002: a typed
``except`` that swallows). The Conformance Gate on this pull request is
expected to fail and name this file as introduced by the change.
"""


def planted_violation() -> None:
    """Swallow an exception on purpose so the gate has something to find."""
    try:
        pass
    except Exception:
        pass
