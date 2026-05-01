# Application-sdk v3 base image
FROM registry.atlan.com/public/app-runtime-base:3

WORKDIR /app

# Copy app dependencies and create venv with all dependencies
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv venv .venv && \
    uv sync --locked --no-install-project

# Copy application code
COPY --chown=appuser:appuser . .

# App-specific environment variables
ENV ATLAN_APP_MODULE=app.mysql:MySQLApp \
    ATLAN_CONTRACT_GENERATED_DIR=app/generated

# Download DAPR components (app-specific)
RUN uv run poe download-components
