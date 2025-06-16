# Atlan PostgreSQL App - Codebase Overview

## Core Architecture

### 1. Application Components
- **FastAPI Server**: Main web application server for handling API requests
- **Temporal**: Workflow orchestration engine for reliable metadata extraction
- **DAPR**: Distributed application runtime for infrastructure abstraction
- **Atlas**: Metadata store integration for entity management

### 2. Directory Structure
```
.
├── app/                      # Core application code
│   ├── activities/          # Business logic and task execution
│   │   ├── __init__.py
│   │   └── metadata_extraction/
│   ├── clients/            # Database connectivity
│   │   └── __init__.py
│   ├── handlers/           # Request processing and workflow triggers
│   ├── transformers/       # Data transformation logic
│   │   └── atlas/         # Atlas entity transformers
│   └── workflows/          # Process orchestration
│       └── metadata_extraction/
├── docs/                    # Documentation
│   ├── images/             # Documentation images and diagrams
│   └── setup/              # Setup and installation guides
├── frontend/               # Frontend assets
│   ├── static/            # Static assets (JS, CSS)
│   └── templates/         # HTML templates
├── tests/                  # Test suite
│   ├── e2e/               # End-to-end tests
│   │   └── test_workflows/
│   └── unit/              # Unit tests
│       └── transformers/
├── .env                    # Environment variables (gitignored)
├── main.py                # Application entry point
├── pyproject.toml        # Project configuration
└── README.md             # Project documentation
```

### 3. Key Components

#### A. Database Client (`app/clients/`)
- Extends BaseSQLClient from application-sdk
- Configures PostgreSQL connection template
- Handles authentication (Basic, IAM)
- Example:
```python
class SQLClient(BaseSQLClient):
    """PostgreSQL client implementation"""

    DB_CONFIG = {
        "template": "postgresql+psycopg://{username}:{password}@{host}:{port}/{database}",
        "required": ["username", "password", "host", "port", "database"],
    }
```

#### B. Activities (`app/activities/metadata_extraction/`)
- Extends BaseSQLMetadataExtractionActivities
- Defines PostgreSQL-specific metadata queries
- Implements extraction logic
- Example:
```python
class PostgresSQLActivities(BaseSQLMetadataExtractionActivities):
    """Activities for PostgreSQL metadata extraction"""

    fetch_database_sql = """
    SELECT datname as database_name
    FROM pg_database
    WHERE datname = current_database();
    """

    fetch_schema_sql = """
    SELECT s.*
    FROM information_schema.schemata s
    WHERE s.schema_name NOT LIKE 'pg_%'
        AND s.schema_name != 'information_schema'
        AND concat(s.CATALOG_NAME, concat('.', s.SCHEMA_NAME)) !~ '{normalized_exclude_regex}'
        AND concat(s.CATALOG_NAME, concat('.', s.SCHEMA_NAME)) ~ '{normalized_include_regex}';
    """

    fetch_table_sql = """
    SELECT t.*
    FROM information_schema.tables t
    WHERE concat(current_database(), concat('.', t.table_schema)) !~ '{normalized_exclude_regex}'
        AND concat(current_database(), concat('.', t.table_schema)) ~ '{normalized_include_regex}'
        {temp_table_regex_sql};
    """
```

#### C. Handler (`app/handlers/`)
- Extends SQLHandler for workflow request handling
- Implements preflight checks and metadata queries
- Example:
```python
class PostgresSQLWorkflowHandler(SQLHandler):
    """Handler for PostgreSQL workflow requests"""

    tables_check_sql = """
    SELECT count(*)
    FROM INFORMATION_SCHEMA.TABLES
    WHERE concat(TABLE_CATALOG, concat('.', TABLE_SCHEMA)) !~ '{normalized_exclude_regex}'
        AND concat(TABLE_CATALOG, concat('.', TABLE_SCHEMA)) ~ '{normalized_include_regex}'
        AND TABLE_SCHEMA NOT IN ('performance_schema', 'information_schema', 'pg_catalog')
    """

    metadata_sql = """
    SELECT schema_name, catalog_name
    FROM INFORMATION_SCHEMA.SCHEMATA
    WHERE schema_name NOT LIKE 'pg_%'
    AND schema_name != 'information_schema'
    """
```

#### D. Workflow (`app/workflows/metadata_extraction/`)
- Uses BaseSQLMetadataExtractionWorkflow
- Orchestrates metadata extraction process
- Example:
```python
async def setup_workflow():
    """Setup and start the PostgreSQL metadata extraction workflow"""

    workflow_client = get_workflow_client(application_name="postgres")
    await workflow_client.load()

    activities = PostgresSQLActivities(
        sql_client_class=SQLClient,
        handler_class=PostgresSQLWorkflowHandler
    )

    worker = Worker(
        workflow_client=workflow_client,
        workflow_classes=[BaseSQLMetadataExtractionWorkflow],
        workflow_activities=BaseSQLMetadataExtractionWorkflow.get_activities(
            activities
        ),
    )

    workflow_args = {
        "credentials": {
            "authType": "basic",
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": os.getenv("POSTGRES_PORT", "5432"),
            "username": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "password"),
            "database": os.getenv("POSTGRES_DATABASE", "postgres"),
        },
        "connection": {
            "connection_name": "test-connection",
            "connection_qualified_name": "default/postgres/1728518400",
        },
        "metadata": {
            "exclude-filter": "{}",
            "include-filter": "{}",
            "temp-table-regex": "",
            "extraction-method": "direct",
            "exclude_views": "true",
            "exclude_empty_tables": "false",
        }
    }

    return await workflow_client.start_workflow(
        workflow_args,
        BaseSQLMetadataExtractionWorkflow
    )
```

### 4. Infrastructure Components

#### A. Temporal
- **Purpose**: Workflow orchestration
- **Features**:
  - Workflow versioning
  - Activity retries with backoff
  - Workflow timeouts
  - Progress tracking

#### B. DAPR
- **Purpose**: Infrastructure abstraction
- **Building Blocks**:
  - State management
  - Secrets handling
  - Service invocation
  - Pub/sub messaging

### 5. Key Features

#### A. Metadata Extraction
- Extract database schema information
- Transform to Atlas format
- Store in object storage
- Handle incremental updates

#### B. Authentication
- Basic authentication
- IAM authentication
- Token management
- Connection pooling

#### C. Observability
- OpenTelemetry integration
- Metrics collection
- Distributed tracing
- Logging

### 6. Development Workflow

#### A. Local Setup
1. Install dependencies (uv)
2. Configure environment
3. Start local services
4. Run application

#### B. Testing
- Unit tests
- Integration tests
- E2E tests
- Test utilities

### 7. Extending for New Databases

#### A. Required Components
1. Database Client
2. SQL Queries
3. Workflow Handler
4. Metadata Activities
5. Atlas Transformers
6. Frontend Support

#### B. Implementation Steps
1. Add SQLAlchemy dialect
2. Create component structure
3. Implement core logic
4. Add tests
5. Update frontend

### 8. Best Practices

#### A. Code Organization
- Modular structure
- Clear separation of concerns
- Consistent naming
- Documentation

#### B. Error Handling
- Graceful degradation
- Retry mechanisms
- Error reporting
- State recovery

#### C. Security
- Secure credential handling
- Token management
- Access control
- Audit logging

### 9. Configuration

#### A. Environment Variables
- Database settings
- Authentication configs
- Service endpoints
- Feature flags

#### B. Application Settings
- Workflow configurations
- Activity timeouts
- Retry policies
- Resource limits