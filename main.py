"""Container entry point for atlan-mysql-app.

In container deployments the SDK runtime imports the App class declared in
the ``ATLAN_APP_MODULE`` env var (``app.mysql:MySQLApp`` — see
``Dockerfile`` and ``atlan.yaml`` → ``deploy.env``) and boots the combined
HTTP handler + worker. This thin script provides the same behaviour when
running the image directly without overriding the command.

For local development use::

    uv run python -m app.run_dev
    # or equivalently:
    uv run python main.py

Both paths go through ``app.run_dev.main`` → ``run_dev_combined`` and
bring up an in-process Temporal runtime + in-process backends for
state / secrets / object storage — no external services required.
"""

from __future__ import annotations

import asyncio

from app.run_dev import main

if __name__ == "__main__":
    asyncio.run(main())
