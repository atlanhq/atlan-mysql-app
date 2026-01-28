"""MySQL app-specific constants."""

import os

# Override APPLICATION_NAME to use "mysql" as connector name
# This ensures the connector name matches the legacy connector
APPLICATION_NAME = os.getenv("ATLAN_APPLICATION_NAME", "mysql")
