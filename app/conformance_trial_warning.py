"""TRIAL ONLY (FND-5029) - do not merge.

A deliberately planted WARN-tier conformance finding (E010: a
``gather(return_exceptions=True)`` whose results are never inspected). The
Conformance Gate on this pull request is expected to PASS and still list it.
"""

import asyncio


async def planted_warning(tasks: list) -> int:
    """Gather with return_exceptions and never look at the exceptions."""
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return len(results)
