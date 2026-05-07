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
#
#   ── SDR (Self-Deployed Runtime) — see sdr-dev/README.md ──
#   make sdr-render       Render sdr-dev/values-override.yaml from .env
#   make sdr-install      helm upgrade --install (requires kubectl context)
#   make sdr-uninstall    helm uninstall (keeps namespace)
#   make sdr-teardown     helm uninstall + delete namespace (full cleanup)
#   make sdr-status       kubectl get pods + helm status
#   make sdr-logs         Tail SDR pod logs
#   make sdr-port-forward Forward SDR pod :8000 → localhost:$(LOCAL_PORT)

.PHONY: install test test-e2e test-e2e-remote test-cov lint format pre-commit \
        dev start-deps stop build clean \
        sdr-render sdr-install sdr-uninstall sdr-teardown sdr-status \
        sdr-logs sdr-port-forward

# ── Configuration ─────────────────────────────────────────────────────────────

REGISTRY   ?= ghcr.io/atlanhq
IMAGE_NAME ?= atlan-mysql-app
TAG        ?= latest

# E2E remote configuration
APP_NAMESPACE          ?= mysql-app
APP_DEPLOYMENT         ?= mysql-server
REMOTE_CREDENTIAL_GUID ?= local-mysql
LOCAL_PORT             ?= 8000
REMOTE_PORT            ?= 8000

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	uv sync --all-extras
	uv run poe download-components

setup-local-creds:
	@CRED_GUID=$${LOCAL_CREDENTIAL_GUID:-local-mysql}; \
	MYSQL_U=$${MYSQL_USER:-root}; \
	MYSQL_P=$${MYSQL_PASSWORD:-}; \
	MYSQL_H=$${MYSQL_HOST:-localhost}; \
	MYSQL_PT=$${MYSQL_PORT:-3306}; \
	mkdir -p local/dapr/secrets; \
	mkdir -p "local/dapr/objectstore/persistent-artifacts/apps/default/credentials/$$CRED_GUID"; \
	echo "{\"$$CRED_GUID\": {\"username\": \"$$MYSQL_U\", \"password\": \"$$MYSQL_P\"}}" > local/dapr/secrets/secrets.json; \
	echo "{\"authType\": \"basic\", \"host\": \"$$MYSQL_H\", \"port\": \"$$MYSQL_PT\", \"credentialSource\": \"direct\"}" > "local/dapr/objectstore/persistent-artifacts/apps/default/credentials/$$CRED_GUID/config.json"; \
	echo "Local Dapr creds configured for $$CRED_GUID (user=$$MYSQL_U)"

# ── Development ───────────────────────────────────────────────────────────────

dev: setup-local-creds start-deps
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
	@echo "Port-forwarding $(APP_NAMESPACE)/$(APP_DEPLOYMENT) → localhost:$(LOCAL_PORT)..."; \
	kubectl port-forward -n $(APP_NAMESPACE) deployment/$(APP_DEPLOYMENT) $(LOCAL_PORT):$(REMOTE_PORT) & \
	kubectl port-forward -n temporal svc/temporal-cluster-internal-frontend-headless 7233:7236 & \
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
	echo "Running e2e tests against $(APP_NAMESPACE)..."; \
	APP_BASE_URL=http://localhost:$(LOCAL_PORT) \
	CREDENTIAL_GUID=$(REMOTE_CREDENTIAL_GUID) \
	uv run pytest tests/e2e/ -v --timeout=600 --tb=short; \
	TEST_EXIT=$$?; \
	kill %1 %2 2>/dev/null; \
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

# ── SDR (Self-Deployed Runtime) ───────────────────────────────────────────────
# Helm-based install used for in-cluster dev/test against a real tenant.
# All knobs come from .env; see sdr-dev/README.md for the variable list.

SDR_DIR                       ?= sdr-dev
SDR_NAMESPACE                 ?= mysql-app-sdr
SDR_VALUES_RENDERED           := $(SDR_DIR)/values-override.yaml
# Source namespace to copy the GHCR pull secret from. The chart references
# `atlan-docker-secret` for image pulls; we copy it from an existing in-cluster
# install (typically a deployed app namespace) so the SDR pod can pull from
# ghcr.io/atlanhq. Override if your cluster has it under a different name.
SDR_PULL_SECRET_NAME          ?= atlan-docker-secret
SDR_PULL_SECRET_SRC_NAMESPACE ?= mysql-sdr-imp01

# All SDR targets re-source .env in a fresh shell so the file is the single
# source of truth — no need for `source .env` between edits, and stale env
# vars from a prior shell can't poison the run. We unset every SDR_* var
# before sourcing so a removed/commented line in .env is honored even when
# the shell still carries the old export.
#
# SDR_RELEASE_NAME is the user-facing knob. Defaults to "mysql-app-sdr-dev".
# Must start with "mysql-app-sdr-" — the suffix after that prefix is what the
# Atlan side uses for the agent / queue (e.g. release "mysql-app-sdr-dev"
# yields agent "mysql-dev" and queue "atlan-mysql-dev").
define SDR_LOAD_ENV
for v in $$(env | sed -n 's/^\(SDR_[A-Z_]*\)=.*/\1/p'); do unset $$v; done; \
set -a; [ -f .env ] && . ./.env; set +a; \
SDR_RELEASE_NAME="$${SDR_RELEASE_NAME:-mysql-app-sdr-dev}"; \
case "$$SDR_RELEASE_NAME" in \
  mysql-app-sdr-?*) ;; \
  *) echo "Error: SDR_RELEASE_NAME must start with 'mysql-app-sdr-' (got: $$SDR_RELEASE_NAME)" >&2; exit 1;; \
esac; \
SDR_DEPLOYMENT_NAME="$${SDR_RELEASE_NAME#mysql-app-sdr-}";
endef

sdr-render:
	@$(SDR_LOAD_ENV) $(SDR_DIR)/render.sh

sdr-install: sdr-render
	@$(SDR_LOAD_ENV) \
	  echo "Ensuring namespace $(SDR_NAMESPACE) and pull secret $(SDR_PULL_SECRET_NAME)..."; \
	  kubectl create namespace $(SDR_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -; \
	  if ! kubectl get secret $(SDR_PULL_SECRET_NAME) -n $(SDR_NAMESPACE) >/dev/null 2>&1; then \
	    echo "  copying $(SDR_PULL_SECRET_NAME) from $(SDR_PULL_SECRET_SRC_NAMESPACE)/..."; \
	    kubectl get secret $(SDR_PULL_SECRET_NAME) -n $(SDR_PULL_SECRET_SRC_NAMESPACE) -o yaml \
	      | sed -e "s/^  namespace: .*/  namespace: $(SDR_NAMESPACE)/" \
	            -e '/resourceVersion:\|uid:\|creationTimestamp:\|annotations:\|kubectl\.kubernetes\.io\/last-applied-configuration:/d' \
	      | kubectl apply -f - || { echo "    secret copy failed — check that $(SDR_PULL_SECRET_NAME) exists in $(SDR_PULL_SECRET_SRC_NAMESPACE)" >&2; exit 1; }; \
	  fi; \
	  echo "Installing $$SDR_RELEASE_NAME in namespace $(SDR_NAMESPACE)..."; \
	  helm upgrade --install $$SDR_RELEASE_NAME $(SDR_DIR)/chart \
	    --namespace $(SDR_NAMESPACE) --create-namespace \
	    --values $(SDR_VALUES_RENDERED)

sdr-uninstall:
	@$(SDR_LOAD_ENV) \
	  helm uninstall $$SDR_RELEASE_NAME --namespace $(SDR_NAMESPACE) || true

sdr-teardown:
	@$(SDR_LOAD_ENV) \
	  echo "Tearing down $$SDR_RELEASE_NAME and namespace $(SDR_NAMESPACE)..."; \
	  helm uninstall $$SDR_RELEASE_NAME --namespace $(SDR_NAMESPACE) || true; \
	  kubectl delete namespace $(SDR_NAMESPACE) --ignore-not-found; \
	  rm -f $(SDR_VALUES_RENDERED)

sdr-status:
	@$(SDR_LOAD_ENV) \
	  echo "── helm status ──"; helm status $$SDR_RELEASE_NAME --namespace $(SDR_NAMESPACE) || true; \
	  echo "── pods ──"; kubectl get pods -n $(SDR_NAMESPACE) -l app.kubernetes.io/instance=$$SDR_RELEASE_NAME

sdr-logs:
	@$(SDR_LOAD_ENV) \
	  kubectl logs -n $(SDR_NAMESPACE) -l app.kubernetes.io/instance=$$SDR_RELEASE_NAME --tail=200 -f

sdr-port-forward:
	@$(SDR_LOAD_ENV) \
	  echo "Forwarding $(SDR_NAMESPACE)/$$SDR_RELEASE_NAME → localhost:$(LOCAL_PORT)..."; \
	  kubectl port-forward -n $(SDR_NAMESPACE) deployment/$$SDR_RELEASE_NAME $(LOCAL_PORT):8000
