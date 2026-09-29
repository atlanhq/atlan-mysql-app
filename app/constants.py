"""
Constants for MySQL metadata extraction.

This module contains constants used across MySQL SQL queries.
"""

import os

# Lives in atlan_mysql_api because the handler reads it too; re-exported here so
# the worker's extraction code keeps one spelling.
from atlan_mysql_api.constants import DATABASE_PLACEHOLDER

__all__ = ["DATABASE_PLACEHOLDER", "TENANT_ID"]

# Atlan tenant ID — used in all transformed JSONL entities
TENANT_ID = os.environ.get("ATLAN_TENANT_ID", "default")
