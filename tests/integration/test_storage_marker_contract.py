"""The storage contract this app's tiers rely on: markers are not data.

Why this lives in a canonical app rather than only in the SDK: the canonical
apps ARE the SDK's release gate — an SDK release is validated by running these
repos' suites across the cloud legs. A storage defect that no canonical
exercises ships green. This file closes one such hole.

The defect (SDK PR #4436, CONNECT-3302 / CONAT-5039). Since 3.46.0 the shared
persist engine (``storage/reference.py::_persist_file``, reached by
``App.upload`` and ``storage.transfer.upload``) stamps a local ``{file}.sha256``
marker beside every file it uploads, as a materialize cache key.
``reference._list_upload_files`` skips those markers when it re-uploads a tree;
``storage/batch.py::upload_prefix::_collect_files`` did not. A marker shipped by
``upload_prefix`` lands on the store-side sidecar key of its own data file — so
the recorded digest stops describing the stored object, and the next download
fails non-retryably with ``[AAF-STR-007] Corrupt artifact detected``.

In production (a connector that calls BOTH primitives over one tree) this cost
13 runs across 12 tenants on 2026-10-18. This app does not currently make that
pairing, so this test is not a regression test for app code — it pins the SDK
behaviour the storage tier depends on, so the same defect cannot reach a release
unnoticed a second time.

Deliberately NOT a race test. In the wild, whether the stale marker wins depends
on ``os.walk`` order and upload concurrency, which is why only some runs failed.
Asserting on the returned key list instead makes it deterministic: shipping the
marker at all is the defect, regardless of which write lands last.

Affected: 3.46.0 .. 3.49.2 (every release carrying the bug). Fixed: 3.50.0.
Verified red at 3.49.2 and green with #4436 applied, on 2026-10-19.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import obstore
import pytest
from application_sdk.storage.batch import upload_prefix
from application_sdk.storage.factory import create_memory_store

pytestmark = pytest.mark.integration


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SDK <=3.49.2 ships local .sha256 markers as data (fixed in 3.50.0, "
        "PR #4436). Expected to fail until this repo's lock reaches 3.50.0 -- "
        "at which point this turns into a strict XPASS failure. That is the "
        "signal to DELETE this xfail marker, leaving the assertion as a "
        "permanent gate."
    ),
)
@pytest.mark.asyncio
async def test_upload_prefix_does_not_ship_local_integrity_markers(
    tmp_path: Path,
) -> None:
    """A re-upload must send the data file and recompute its digest, nothing else."""
    store = create_memory_store()
    source = tmp_path / "raw" / "entities"
    source.mkdir(parents=True)

    artifact = source / "result-0.json"
    original = b'{"rows": 1}\n'
    artifact.write_bytes(original)

    # What App.upload / transfer.upload leave behind: a marker holding the
    # digest of the bytes they sent.
    marker = artifact.with_name(artifact.name + ".sha256")
    marker.write_text(hashlib.sha256(original).hexdigest())

    # The activity then rewrites its own output. The marker is now stale, and
    # the tree is re-uploaded with a directory primitive.
    rewritten = b'{"rows": 2}\n'
    artifact.write_bytes(rewritten)

    uploaded = await upload_prefix(
        local_dir=str(tmp_path / "raw"),
        prefix="remote",
        store=store,
        normalize=False,
        retain_local_copy=True,
    )

    shipped = [key for key in uploaded if key.endswith(".sha256")]
    assert not shipped, (
        f"upload_prefix shipped local integrity markers as data objects: "
        f"{shipped}. Each lands on the store-side sidecar key of its own data "
        f"file, so the recorded digest stops describing the stored object and "
        f"the next download fails with AAF-STR-007."
    )

    # The surviving sidecar must describe what is actually stored.
    recorded = bytes(
        await (
            await obstore.get_async(store, "remote/entities/result-0.json.sha256")
        ).bytes_async()
    )
    assert recorded.decode().strip() == hashlib.sha256(rewritten).hexdigest()
