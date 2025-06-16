# Application Architecture

The application is a FastAPI-based microservice built using the [Application SDK](https://github.com/atlanhq/application-sdk). It's designed to extract and transform metadata from PostgreSQL databases into Atlas format.

The SDK integration provides:
1. Temporal workflow orchestration
2. SQL metadata extraction capabilities
3. Atlas metadata transformation
4. OpenTelemetry (OTeL) observability
5. Health check endpoints
6. Configuration management

## Core Components

### Workflow Engine
The application uses Temporal for workflow orchestration, which provides:
- Reliable execution of long-running operations
- Automatic retries and error handling
- Activity state management
- Parallel execution capabilities

### SQL Metadata Extraction
The application supports various authentication methods for PostgreSQL:
- Basic authentication (username/password)
- IAM authentication (for AWS RDS)
- IAM Role-based authentication

### Atlas Transformation
Extracted metadata is transformed into Atlas format, supporting:
- Tables
- Views
- Materialized Views
- Columns
- Procedures

## File Structure

### Root Directory
- `main.py` - Application entrypoint that initializes:
  - Temporal workflow client
  - SQL metadata extraction activities
  - Worker configuration
  - FastAPI application setup
- `pyproject.toml` - Project configuration and dependencies

### App Directory (`app/`)
- `clients/` - Database client implementations
  - SQL client with connection string generation
  - Authentication handling
- `sql/` - SQL queries for metadata extraction
- `transformers/` - Atlas transformation logic
  - Table transformers
  - Column transformers
  - Custom attribute mapping

### Test Directory (`tests/`)
- `unit/` - Unit tests for components
- `e2e/` - End-to-end workflow tests
- Test utilities and fixtures

### Frontend Directory (`frontend/`)
Contains the web interface for:
- Connection configuration
- Workflow monitoring
- Metadata visualization

## Development Tools
- uv for dependency management
- Pre-commit hooks for code quality
- Pytest for testing
- Ruff and Pyright for linting and type checking

## Configuration
The application is configurable through:
- Environment variables (see `.env.example`)
- Runtime workflow parameters

For detailed SDK capabilities and integration points, refer to the [Application SDK documentation](https://github.com/atlanhq/application-sdk).