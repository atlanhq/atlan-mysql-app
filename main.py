"""MySQL App — entry point.

Uses external Dapr + Temporal (``run_combined_mode``) when ``DAPR_HTTP_PORT``
is set (CI / docker-compose mode).  Falls back to the zero-dependency embedded
mode (``run_dev_combined``) for local development.
"""

import asyncio
import os

from app.mysql import MySQLApp

if __name__ == "__main__":
    if os.environ.get("DAPR_HTTP_PORT"):
        # External Dapr sidecar is running — use production-equivalent combined mode.
        # Temporal host defaults to localhost:7233; override via ATLAN_TEMPORAL_HOST.
        from application_sdk.main import AppConfig, run_combined_mode

        config = AppConfig(
            mode="combined",
            app_module="app.mysql:MySQLApp",
            temporal_host=os.environ.get("ATLAN_TEMPORAL_HOST", "localhost:7233"),
        )
        asyncio.run(run_combined_mode(config))
    else:
        # No external Dapr — boot embedded Dapr + Temporal for local dev.
        from application_sdk.main import run_dev_combined

        asyncio.run(run_dev_combined(MySQLApp))
