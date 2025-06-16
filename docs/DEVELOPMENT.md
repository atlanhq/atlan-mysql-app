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
    - [Start the dependencies](#start-the-dependencies)
    - [Run the application](#run-the-application)
    - [Development Commands](#development-commands)
- [Using VSCode or Cursor](#development-with-vscode-or-cursor)
- [Working with the frontend (Optional)](#working-with-the-frontend-optional)


## Prerequisites

### Development Tools
_If you are using the Atlan CLI to create a new application, you can skip this section._
- Setup the local development environment via the [setup guide](./setup)

## Development with VSCode or Cursor
1. Follow the above steps until you have the dependencies running.
2. Add the following settings to the `.vscode/launch.json` file
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Main with uv",
            "type": "python",
            "request": "launch",
            "module": "uv",
            "args": ["run", "python", "main.py"],
            "console": "integratedTerminal",
            "justMyCode": true
        },
        {
            "name": "Python: Debug Unit Tests",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/.venv/bin/pytest",
            "args": [
                "-v"
            ],
            "cwd": "${workspaceFolder}/tests/unit",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        }
    ]
}
```
> This will create a new configuration for running the FastAPI server.
- You can navigate to the Run and Debug section in the IDE to run the configurations of your choice.


## Working with the frontend (Optional)

- Feel free to work on the frontend in the `frontend` directory.
