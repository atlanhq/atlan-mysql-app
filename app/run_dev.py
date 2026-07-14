"""Local development entry for atlan-mysql-app.

Boots the SDK's combined HTTP handler + worker via ``run_dev_combined`` —
in-process workflow runtime, in-process backends for state / secrets /
object storage. No external Temporal CLI, no Dapr sidecar, no Redis.
The only prerequisite is Python + ``uv``.

Run::

    uv run python -m app.run_dev
    # or, via the thin entry-point shim:
    uv run python main.py

The server comes up on http://localhost:8000 and the embedded Temporal Web
UI on http://localhost:8233 (watch the workflow timeline — the first activity
is the injected ``mysql:preflight`` gate).

Trigger the metadata-extraction entrypoint::

    curl -X POST http://localhost:8000/workflows/v1/start \\
      -H "Content-Type: application/json" \\
      -d '{
        "credentials": [
          {"key": "host", "value": "localhost"},
          {"key": "port", "value": "3306"},
          {"key": "username", "value": "root"},
          {"key": "password", "value": ""},
          {"key": "authType", "value": "basic"}
        ],
        "connection": {
          "attributes": {
            "name": "mysql-local",
            "qualified_name": "default/mysql/local"
          }
        }
      }'

Fetch the result (use the ``workflow_id`` from the response above)::

    curl http://localhost:8000/workflows/v1/result/<workflow_id>

In production the container is launched by the v3 base image's CLI with
``ATLAN_APP_MODULE=app.mysql:MySQLApp`` (see ``Dockerfile`` and
``atlan.yaml`` → ``deploy.env``) — that path goes through
``application_sdk.main:run_combined_mode`` with the real Dapr-backed
secret store and object store. This dev-mode runner is local-only.
"""

from __future__ import annotations

import asyncio

from application_sdk.main import run_dev_combined

from app.mysql import MySQLApp


async def main() -> None:
    """Boot the dev runtime in-process and run the app against it.

    ``example_input`` only shapes the SDK's ``POST /workflows/v1/start``
    schema doc for local exploration — actual workflow input comes from
    the body of the curl request shown in the module docstring.
    """
    await run_dev_combined(
        MySQLApp,
        temporal_ui=True,
        example_input={
            "credentials": [
                {"key": "host", "value": "localhost"},
                {"key": "port", "value": "3306"},
                {"key": "username", "value": "root"},
                {"key": "password", "value": ""},
                {"key": "authType", "value": "basic"},
            ],
            "connection": {
                "attributes": {
                    "name": "mysql-local",
                    "qualified_name": "default/mysql/local",
                }
            },
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
