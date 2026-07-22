"""Global test configuration."""

import os

# mutmut sandbox compat (mutation-testing lane): mutmut 3.6.0's
# record_trampoline_hit() resolves the relative [tool.mutmut] source_paths
# against the current working directory on every mutated-function call
# during its stats phase, so any test that chdirs crashes with
# FileNotFoundError. The resolve only feeds the max_stack_depth feature,
# which we leave at its disabled default — replace with the equivalent
# minus the resolve. Only active under `mutmut run`; plain pytest runs
# never import mutmut.
if os.environ.get("MUTANT_UNDER_TEST") is not None:
    import mutmut
    import mutmut.mutation.trampoline as _trampoline

    def _record_trampoline_hit_without_cwd_resolve(name: str) -> None:
        assert not name.startswith("src."), (
            "Failed trampoline hit. Module name starts with `src.`, which is invalid"
        )
        mutmut._stats.add(name)

    setattr(  # noqa: B010 — name is not exported; setattr avoids pyright private-import error
        _trampoline, "record_trampoline_hit", _record_trampoline_hit_without_cwd_resolve
    )


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_boto3_default_session():
    """Prevent mock leakage through boto3's module-global default session.

    boto3.client(...) lazily creates boto3.DEFAULT_SESSION — a module-level
    global. Tests that patch boto3.Session leak the MagicMock into that
    global, so every later boto3.client() call in the same process silently
    reuses the mock (surfaced by mutation testing, which re-runs the suite
    in one process; also a hazard for any later test using real boto3).
    """
    yield
    try:
        import boto3  # noqa: PLC0415

        boto3.DEFAULT_SESSION = None
    except ImportError:
        pass
