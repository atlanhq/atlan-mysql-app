# syntax=docker/dockerfile:1
FROM registry.atlan.com/public/app-runtime-base:3

WORKDIR /app

# Copy lock files first for dependency caching
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md ./

# Install dependencies (excluding the project itself) into a new venv
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv venv .venv && \
    uv sync --locked --no-install-project --no-dev

# Copy application code
COPY --chown=appuser:appuser app/ app/

ENV ATLAN_APP_MODULE=app.mysql:MySQLApp
ENV ATLAN_CONTRACT_GENERATED_DIR=/app/app/generated

# Download Dapr components
RUN uv run poe download-components
