# Define variables
APP_NAME := phoenix-postgres-app

# Phony targets
.PHONY: install start-deps run run-hot-reload run-all run-marketplace stop-marketplace

# Attempt to include .env file if it exists
-include .env

# Default values (will be used if .env doesn't exist or variables are not set)
ATLAN_APP_HTTP_HOST ?= 0.0.0.0
ATLAN_APP_HTTP_PORT ?= 8000
ATLAN_APP_DASHBOARD_HTTP_HOST ?= 0.0.0.0
ATLAN_APP_DASHBOARD_HTTP_PORT ?= 8050
ATLAN_DAPR_APP_PORT ?= 3000
ATLAN_DAPR_HTTP_PORT ?= 3500
ATLAN_DAPR_GRPC_PORT ?= 50001
ATLAN_DAPR_METRICS_PORT ?= 3100
ATLAN_TEMPORAL_UI_ENABLED?=true
ATLAN_TEMPORAL_HOST ?= 127.0.0.1
ATLAN_TEMPORAL_PORT ?= 7233
ATLAN_TEMPORAL_UI_HOST ?= 127.0.0.1
ATLAN_TEMPORAL_UI_PORT ?= 8233
ATLAN_TEMPORAL_METRICS_PORT ?= 8234
ATLAN_TENANT_ID ?= "default"
ATLAN_APPLICATION_NAME ?= "postgres"
ENABLE_OTLP_LOGS ?= false
# Start Temporal locally
start-temporal-dev:
	@if [ "$(ATLAN_TEMPORAL_UI_ENABLED)" = true ]; then \
		temporal server start-dev --db-filename /tmp/temporal.db --ip $(ATLAN_TEMPORAL_HOST) --port $(ATLAN_TEMPORAL_PORT) --ui-ip $(ATLAN_TEMPORAL_UI_HOST) --ui-port $(ATLAN_TEMPORAL_UI_PORT) --metrics-port $(ATLAN_TEMPORAL_METRICS_PORT); \
	else \
		temporal server start-dev --db-filename /tmp/temporal.db --ip $(ATLAN_TEMPORAL_HOST) --port $(ATLAN_TEMPORAL_PORT) --metrics-port $(ATLAN_TEMPORAL_METRICS_PORT) --headless; \
	fi

# Start Dapr
start-dapr:
	dapr run --app-id app --app-port $(ATLAN_DAPR_APP_PORT) --dapr-http-port $(ATLAN_DAPR_HTTP_PORT) --dapr-grpc-port $(ATLAN_DAPR_GRPC_PORT) --dapr-http-max-request-size 1024 --resources-path .venv/src/application-sdk/components

# Start all services in detached mode
start-deps:
	@echo "Starting all services in detached mode..."
	make start-dapr &
	make start-temporal-dev &
	@echo "Services started. Proceeding..."

# Install dependencies
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

# Define variables
MARKETPLACE_DIR := ../atlan-marketplace-app
MARKETPLACE_LOG := $(MARKETPLACE_DIR)/output.log
MARKETPLACE_PID := $(MARKETPLACE_DIR)/marketplace.pid

# Run the marketplace app
run-marketplace:
	@if [ ! -d "$(MARKETPLACE_DIR)" ]; then \
		echo "Error: $(MARKETPLACE_DIR) not found. Please clone it first."; \
		exit 1; \
	fi
	@command -v poetry >/dev/null 2>&1 || { echo "Poetry is required but not installed. Aborting." >&2; exit 1; }
	@rm -f $(MARKETPLACE_LOG)
	cd $(MARKETPLACE_DIR) && poetry install || { echo "Poetry install failed"; exit 1; }
	@if [ -f "$(MARKETPLACE_PID)" ]; then \
		echo "Marketplace app is already running. Skipping start."; \
	else \
		cd $(MARKETPLACE_DIR) && nohup python3 main.py > $(MARKETPLACE_LOG) 2>&1 & echo $$! > $(MARKETPLACE_PID); \
		echo "Marketplace app started."; \
	fi

stop-marketplace:
	@if [ -f "$(MARKETPLACE_PID)" ]; then \
		kill $$(cat $(MARKETPLACE_PID)) && rm -f $(MARKETPLACE_PID); \
		echo "Marketplace app stopped."; \
	else \
		echo "Marketplace app is not running."; \
	fi

run-all:
	@echo "Starting marketplace app..."
	$(MAKE) run-marketplace
	@echo "Starting local application..."
	$(MAKE) run-app

# Run the application
run-app:
	POETRY_PLUGIN_DOTENV_LOCATION=".env" \
	poetry run python main.py

run-dev:
	POETRY_PLUGIN_DOTENV_LOCATION=".env.dev" \
	poetry run python main.py

# Run the application with profiling
run-with-profile:
	POETRY_PLUGIN_DOTENV_LOCATION=".env" \
	poetry run scalene --profile-all --cli --outfile scalene.json --json main.py

# Run the application and dashboard
run:
	@echo "Starting local application..."
	$(MAKE) run-app

run-hot-reload:
	@echo "Starting local application with hot-reload..."
	poetry run watchmedo auto-restart \
		--patterns="*.py" \
		--recursive \
		--directory="." \
		-- make run-app

# Stop all services
stop-all:
	@echo "Running scalene cleanup..."
	@python .github/scripts/cleanup_scalene.py || true
	@echo "Stopping all detached processes..."
	@pkill -f "temporal server start-dev" || true
	@pkill -f "dapr run --app-id app" || true
	@pkill -f "python main.py" || true
	@pkill -f "scalene.*main.py" || true
	@sleep 2  # Add a small delay to ensure processes have time to finish
	$(MAKE) stop-marketplace
	@echo "All detached processes stopped."

