"""MySQL App — v3 SDK entry point."""

import asyncio

from application_sdk.main import run_dev_combined

from app.mysql import MySQLApp

if __name__ == "__main__":
    asyncio.run(run_dev_combined(MySQLApp))
