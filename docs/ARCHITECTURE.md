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
  - `const.py` - Contains the constants used in the application.
  - `workflow.py` - Contains the implementation of the `SQLWorkflowInterface`.
- `tests/` - Contains the tests for the application.
- `frontend/` - Contains the frontend code for the application.