# Application Architecture

The application runs as a FastAPI microservice and is built using the [Phoenix Application SDK](https://github.com/atlanhq/application-sdk).

The SDK integration allows it to expose:
1. OTeL routes
2. SQL routes
3. System Check routes
4. Workflow routes and more.

> [!TIP]
> Head over to the [SDK documentation](https://github.com/atlanhq/application-sdk) for more details on capabilities.

## File Structure
- `main.py` - The entrypoint of the application.
  - The application initializes the SDK here and configures what routes it wants the SDK to add
- `app/` - The core functionality of the application.
  - `const.py` - Contains the constants used in the application, including MySQL-specific SQL queries
  - `workflow.py` - Contains the implementation of the `SQLWorkflowInterface`
  - `clients/` - Contains database client implementations
    - `mysql/` - MySQL-specific client implementation
  - `handlers/` - Contains workflow handlers
    - `mysql/` - MySQL-specific workflow handler
  - `workflows/` - Contains workflow implementations
    - `metadata_extraction/` - Contains metadata extraction workflows
      - `mysql/` - MySQL-specific metadata extraction workflow
  - `activities/` - Contains activity implementations
    - `metadata_extraction/` - Contains metadata extraction activities
      - `mysql/` - MySQL-specific metadata extraction activities
  - `transformers/` - Contains Atlas transformers
    - `atlas/` - Contains Atlas entity transformers
      - `mysql/` - MySQL-specific Atlas transformers
- `tests/` - Contains the tests for the application.
- `frontend/` - Contains the frontend code for the application.

## MySQL Components
The application includes several MySQL-specific components:

1. **MySQL Client** (`app/clients/mysql/`)
   - Handles MySQL database connections
   - Implements MySQL-specific connection parameters
   - Manages MySQL session handling

2. **MySQL Workflow Handler** (`app/handlers/mysql/`)
   - Manages MySQL workflow execution
   - Handles MySQL-specific metadata extraction
   - Implements MySQL connection validation

3. **MySQL Metadata Extraction** (`app/workflows/metadata_extraction/mysql/`)
   - Extracts database metadata
   - Extracts schema metadata
   - Extracts table metadata
   - Extracts column metadata
   - Extracts procedure metadata

4. **MySQL Atlas Transformers** (`app/transformers/atlas/mysql/`)
   - Transforms MySQL database entities
   - Transforms MySQL schema entities
   - Transforms MySQL table entities
   - Transforms MySQL column entities
   - Transforms MySQL procedure entities