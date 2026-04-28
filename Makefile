# MySQL Connector — Makefile (v3 SDK)
#
#   make install          Install deps + Dapr components
#   make dev              Start Temporal + app (local dev)
#   make test             Run unit tests
#   make test-e2e         Run E2E tests (needs running app)
#   make test-e2e-remote  Port-forward vcluster app + run E2E tests
#   make test-cov         Unit tests with coverage
#   make generate         Regenerate PKL contract artifacts
#   make build            Build Docker image
#   make lint             Run ruff linter
#   make format           Auto-format code
#   make pre-commit       Run all pre-commit hooks

.PHONY: install test test-e2e test-e2e-remote test-cov lint format pre-commit \
        dev start-deps stop build clean

# ── Configuration ─────────────────────────────────────────────────────────────

REGISTRY   ?= ghcr.io/atlanhq
IMAGE_NAME ?= atlan-mysql-app
TAG        ?= latest

# E2E remote configuration
APP_NAMESPACE   ?= mysql-app
APP_DEPLOYMENT  ?= mysql-server
LOCAL_PORT      ?= 8000
REMOTE_PORT     ?= 8000

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	uv sync --all-extras
	uv run poe download-components

# ── Development ───────────────────────────────────────────────────────────────

dev: start-deps
	DAPR_HTTP_PORT=3500 DAPR_GRPC_PORT=50001 uv run python main.py

start-deps:
	uv run poe stop-deps || true
	uv run poe start-deps

stop:
	uv run poe stop-deps

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	uv sync --extra test --quiet
	uv run pytest tests/unit/ -v --tb=short

test-e2e:
	uv run pytest tests/e2e/ -v --timeout=600 --tb=short

test-e2e-remote:
	@echo "Port-forwarding $(APP_NAMESPACE)/$(APP_DEPLOYMENT) → localhost:$(LOCAL_PORT)..."
	@kubectl port-forward -n $(APP_NAMESPACE) deployment/$(APP_DEPLOYMENT) $(LOCAL_PORT):$(REMOTE_PORT) & \
	PF_PID=$$!; \
	READY=0; \
	for i in $$(seq 1 30); do \
		if curl -sf http://localhost:$(LOCAL_PORT)/server/health > /dev/null 2>&1; then \
			READY=1; break; \
		fi; \
		sleep 1; \
	done; \
	if [ "$$READY" = "0" ]; then \
		echo "Port-forward failed"; kill $$PF_PID 2>/dev/null; exit 1; \
	fi; \
	echo "Running e2e tests..."; \
	uv run pytest tests/e2e/ -v --timeout=600 --tb=short; \
	TEST_EXIT=$$?; \
	kill $$PF_PID 2>/dev/null; \
	exit $$TEST_EXIT

test-cov:
	uv sync --extra test --quiet
	uv run pytest tests/unit/ --cov=app --cov-report=term-missing --cov-report=html

# ── Code Quality ──────────────────────────────────────────────────────────────

lint:
	uv run ruff check app/ tests/

format:
	uv run ruff format app/ tests/
	uv run ruff check --fix app/ tests/

pre-commit:
	uv run pre-commit run --all-files

# ── Build ─────────────────────────────────────────────────────────────────────

build:
	docker build -t $(REGISTRY)/$(IMAGE_NAME):$(TAG) .

clean:
	rm -rf .pytest_cache htmlcov .coverage local/dapr/objectstore/artifacts
