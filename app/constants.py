"""
Constants for MySQL metadata extraction.

This module contains constants used across MySQL SQL queries.
"""

import os

# Database placeholder used when DATABASE() returns NULL
# This is MySQL's default placeholder when no database is specified in the connection
DATABASE_PLACEHOLDER = "def"

# Atlan tenant ID — used in all transformed JSONL entities
TENANT_ID = os.environ.get("ATLAN_TENANT_ID", "default")
