# Define variables
APP_NAME := phoenix-mysql-app

# Phony targets
.PHONY: install start-deps run

# Attempt to include .env file if it exists
-include .env

# Default values (will be used if .env doesn't exist or variables are not set)
APP_HTTP_HOST ?= 0.0.0.0
APP_HTTP_PORT ?= 8000
APP_DASHBOARD_HTTP_HOST ?= 0.0.0.0
APP_DASHBOARD_HTTP_PORT ?= 8050
DAPR_APP_PORT ?= 3000
DAPR_HTTP_PORT ?= 3500
DAPR_GRPC_PORT ?= 50001

# Run Temporal locally
start-temporal-dev:
	temporal server start-dev --db-filename /tmp/temporal.db

start-dapr:
	dapr run --app-id app --app-port $(DAPR_APP_PORT) --dapr-http-port $(DAPR_HTTP_PORT) --dapr-grpc-port $(DAPR_GRPC_PORT) --dapr-http-max-request-size 1024 --resources-path .venv/src/application-sdk/components

start-deps:
	@echo "Starting all services in detached mode..."
	make start-dapr &
	make start-temporal-dev &
	@echo "Services started. Proceeding..."

install:
	# Setup Mac dependencies
	./docs/scripts/setup_mac.sh
	# Configure git to use https instead of ssh or git
	@if git ls-remote git@github.com:atlanhq/application-sdk.git > /dev/null 2>&1; then \
		echo "Git is configured to use SSH Protocol"; \
	elif git ls-remote https://github.com/atlanhq/application-sdk.git > /dev/null 2>&1; then \
		echo "Git is configured to use HTTPS Protocol. Configuring to use HTTPS instead..."; \
		git config --global url."https://github.com/".insteadOf "git@github.com:"; \
	else \
		echo "Git is not configured to use SSH or Git Protocol. Please configure Git to use SSH or Git Protocol."; \
		exit 1; \
	fi
	# Configure poetry to use project-specific virtualenv
	poetry config virtualenvs.in-project true

	# Install the dependencies
	poetry install -vv
	poetry update application-sdk --dry-run

	# Activate the virtual environment and install pre-commit hooks
	poetry run pre-commit install

# Run the application
run-app:
	HOST=$(APP_HTTP_HOST) \
 	PORT=$(APP_HTTP_PORT) \
 	OTEL_EXPORTER_OTLP_ENDPOINT="http://$(APP_HTTP_HOST):$(APP_HTTP_PORT)/telemetry" \
	OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf" \
	OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true \
	OTEL_PYTHON_EXCLUDED_URLS="/telemetry/.*,/system/.*" \
	poetry run ./.venv/bin/opentelemetry-instrument --traces_exporter otlp --metrics_exporter otlp --logs_exporter otlp --service_name mysql-application python main.py

run-dashboard:
	PYTHONPATH=./.venv/src/application-sdk/ poetry run python .venv/src/application-sdk/dashboard/app.py

run:
	@echo "Starting local dashboard..."
	$(MAKE) run-dashboard &
	@echo "Starting local application..."
	$(MAKE) run-app

stop-all:
	@echo "Stopping all detached processes..."
	@pkill -f "temporal server start-dev" || true
	@pkill -f "dapr run --app-id app" || true
	@pkill -f "python main.py" || true        # For run-app
	@pkill -f "python .venv/src/application-sdk/dashboard/app.py" || true  # For run-dashboard
	@echo "All detached processes stopped."
