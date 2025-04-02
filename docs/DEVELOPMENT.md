# Development

### How does this work?
_If you are using the Atlan CLI to create a new application, you can skip this section._
- There are 3 main components to this application:
    - **Temporal**: This is the workflow engine that is used to schedule and execute the workflow.
    - **DAPR**: This is application runtime that is used to abstract the underlying infrastructure and provide a set of building blocks for the application. In this case, it is used to abstract the object store, secrets manager and state manager.
    - **Application Server** - This is the application that is used to expose endpoints that are used to trigger the workflow via the frontend, view logs, metrics and traces and much more.

> This guide will walk you through the steps to setup the local development environment and start contributing to the project.

**Table of Contents**
- [Prerequisites](#prerequisites)
    - [Development Tools](#development-tools)
- [Using VSCode or Cursor](#development-with-vscode-or-cursor)
- [Working with the frontend (Optional)](#working-with-the-frontend-optional)
- [Using Intellij IDEA](#using-intellij-idea)
  - [Add OTel agent during IntelliJ run](#add-otel-agent-during-intellij-run)
- [Advanced Configuration](#advanced-configuration)
  - [Changing storage of telemetry data](#changing-storage-of-telemetry-data)


## Prerequisites

### Development Tools
_If you are using the Atlan CLI to create a new application, you can skip this section._
- Setup the local development environment on [Mac](./SETUP_MAC.md)

## Development with VSCode or Cursor
1. Follow the above steps (1-5) to install the dependencies and start the platform.
2. Add the following settings to the `.vscode/launch.json` file
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: FastAPI Server",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/main.py"
        },
        {
            "name": "Python: Debug Tests",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/.venv/bin/pytest",
            "args": [
                "-v"
            ],
            "cwd": "${workspaceFolder}",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
    ]
}
```
> This will create a new configuration for running the FastAPI server.
- You can navigate to the Run and Debug section in the IDE to run the configurations of your choice.


## Working with the frontend (Optional)

- Feel free to work on the frontend in the `frontend` directory.
- In case you need to update the frontend static files path, you can update it in the `main.py` file.


## Using Intellij IDEA
1. Open the project in Intellij IDEA PyCharm
2. Create a new run configuration for the project
3. Set the script path to `.venv/bin/fastapi`
4. Set the parameters to `dev main.py`
5. The application support auto-reload, so you can make changes to the code and the server will automatically restart


### Add OTel agent during IntelliJ run
1. Create a new run configuration for the project
2. Set the script path to `.venv/bin/opentelemetry-instrument`
3. Set parameters to `--traces_exporter otlp --metrics_exporter otlp --logs_exporter otlp --service_name mysql-app python main.py`
4. Add environment variable `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000/telemetry;OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf;PYTHONUNBUFFERED=1;OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true;OTEL_PYTHON_EXCLUDED_URLS=/telemetry/.*,/system/.*`
5. Run the configuration

## Advanced Configuration

### Changing storage of telemetry data
The SDK uses SQLite as the default storage for telemetry data using SQLAlchemy and the SQLite file is stored in `/tmp/app.db`.
You can change the storage to any database with SQLAlchemy compatibility by setting the `SQLALCHEMY_DATABASE_URI` and `SQLALCHEMY_CONNECT_ARGS` environment variables and installing the SQLAlchemy compatible database driver.

