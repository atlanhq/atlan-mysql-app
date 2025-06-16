# MySQL Client Configuration

This directory contains the MySQL client implementation for the Atlan MySQL App.

## Overview

The `SQLClient` class extends `AsyncBaseSQLClient` from the Atlan Application SDK and provides MySQL-specific database connectivity configuration.

## Configuration

### Connection Template

```python
DB_CONFIG = {
    "template": "mysql+aiomysql://{username}:{password}@{host}:{port}/{database}",
    "required": ["username", "password", "host", "port", "database"],
    "defaults": {
        "connect_timeout": 5,
        "charset": "utf8mb4",
    },
}
```

### Connection Parameters

- **template**: Uses the aiomysql driver for MySQL connectivity
- **required fields**: All database connection parameters must be provided
- **defaults**: Default connection timeout and UTF-8 character encoding

## Usage Example

```python
from app.clients import SQLClient

# Initialize client
client = SQLClient()

# Set credentials
client.credentials = {
    "username": "atlan_user",
    "password": "atlan_password",
    "host": "localhost",
    "port": "3306",
    "extra": {"database": "test_db"},
    "authType": "basic"
}

# Generate connection string
connection_string = client.get_sqlalchemy_connection_string()
print(connection_string)
# Output: mysql+aiomysql://atlan_user:atlan_password@localhost:3306/test_db?charset=utf8mb4&connect_timeout=5
```

## Supported Authentication

Currently supports basic authentication with username and password. The client expects credentials in the following format:

```python
credentials = {
    "username": "database_username",
    "password": "database_password", 
    "host": "database_host",
    "port": "database_port",
    "extra": {
        "database": "database_name"
    },
    "authType": "basic"
}
```

## Dependencies

- **aiomysql**: Asynchronous Python MySQL client library
- **SQLAlchemy**: Database abstraction layer
- **Atlan Application SDK**: Base client classes

## Notes

- The client uses UTF-8 encoding by default for proper handling of international characters
- Connection timeout is set to 5 seconds to prevent hanging connections
- The aiomysql driver is chosen for its asynchronous capabilities and MySQL compatibility 