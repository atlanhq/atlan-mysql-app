<p align="center">
  <img src="./docs/images/mysql_logo.svg" alt="MySQL Logo" width="200" height="auto">
</p>

# MySQL Application

[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Tests](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/atlanhq/atlan-mysql-app/actions/workflows/unit-tests.yml)
[![Image 1](https://drive.google.com/uc?export=view&id=132GfsP8_dnVR7LyNf24SCrapN1tULeTJ)](https://drive.google.com/file/d/132GfsP8_dnVR7LyNf24SCrapN1tULeTJ/view?usp=sharing)
[![Image 2](https://drive.google.com/uc?export=view&id=1MbmhFnTXugIUFdjvMzX6Tr5O_ewTzP92)](https://drive.google.com/file/d/1MbmhFnTXugIUFdjvMzX6Tr5O_ewTzP92/view?usp=sharing)

MySQL application is designed to interact with a MySQL database and perform actions on it. The application is built using the [Atlan Python Application SDK](https://github.com/atlanhq/application-sdk) and is intended to run on the Atlan Platform.

This application has two components:

- FastAPI server that exposes REST API to interact with the application.
- A workflow that runs on the Atlan platform that extracts metadata from a MySQL database, transforms it and pushes it to an object store.

https://github.com/user-attachments/assets/0ce63557-7c62-4491-96b9-1134a1ceadd6

## Table of contents

- [Usage](#usage)
- [Features](#features)
- [Extending this application to other SQL sources](#extending-this-application-to-other-sql-sources)
- [Development](#development)
- [Architecture](./docs/ARCHITECTURE.md)

## Usage

### Setting up your environment

1. Clone the repository:
   ```bash
   git clone https://github.com/atlanhq/atlan-mysql-app.git
   cd atlan-mysql-app
   ```

2. Follow the setup instructions for your platform:
   - [Automatic Setup](./.cursor/rules/setup.mdc) - Automatically detects your OS and provides the appropriate guide
   - [macOS Setup Guide](https://github.com/atlanhq/application-sdk/blob/main/docs/docs/setup/MAC.md)
   - [Linux Setup Guide](https://github.com/atlanhq/application-sdk/blob/main/docs/docs/setup/LINUX.md)
   - [Windows Setup Guide](https://github.com/atlanhq/application-sdk/blob/main/docs/docs/setup/WINDOWS.md)

3. Install dependencies:
   ```bash
   uv sync --all-groups
   ```

4. Download required components:
   ```bash
   uv run poe download-components
   ```

5. Start the MySQL database (in a separate terminal):
   ```bash
   docker-compose -f docker-compose.mysql.yml up -d
   ```

6. Start the dependencies (in a separate terminal):
   ```bash
   uv run poe start-deps
   ```

7. That loads all required dependencies. To run, you just run the command in the main terminal:
   ```bash
   uv run main.py
   ```

### MySQL Connection Details

When the Docker container is running, you can connect to MySQL using these credentials:

- **Host**: `localhost`
- **Port**: `3306`
- **Username**: `atlan_user`
- **Password**: `atlan_password`
- **Database**: `test_db`

The container also includes sample data with tables, views, and stored procedures for testing.

## Component Structure

- `app/clients`: Database client implementations
- `app/transformers`: Metadata transformation logic (refer [RDBMS models](https://developer.atlan.com/models/rdbms/))
- `app/sql`: SQL query templates

## Features

1. Extract metadata from a MySQL database, transform and push to an object store
2. FastAPI-based REST API interface
3. OpenTelemetry integration for metrics, traces and logs
4. Basic Authentication support

## Extending this application to other SQL sources

1. Make sure you add the required SQLAlchemy dialect using uv. For ex. to add Snowflake dialect, `uv add snowflake-sqlalchemy`
2. Update SQL queries in [`sql`](app/sql) directory to match the target database's system tables and syntax
3. Update the DB_CONFIG in the [`app/clients`](app/clients) directory with the appropriate connection template
4. Run the application using the development guide
5. Update the tests in the [`tests`](tests) directory

### Example: From PostgreSQL to MySQL

This application was converted from PostgreSQL to MySQL by:
- Changing the connection template from `postgresql+psycopg://` to `mysql+pymysql://`
- Converting PostgreSQL system catalog queries (pg_class, pg_namespace) to MySQL information_schema queries
- Updating regex syntax from PostgreSQL (`!~`) to MySQL (`NOT REGEXP`)
- Replacing PostgreSQL-specific functions with MySQL equivalents

## Development

- [Development and Quickstart Guide](./docs/DEVELOPMENT.md)
- This application is just an SQL application implementation of Atlan's [Python Application SDK](https://github.com/atlanhq/application-sdk)
  - Please refer to the [examples](https://github.com/atlanhq/application-sdk/tree/main/examples) in the SDK to see how to use the SDK to build different applications on the Atlan Platform.
