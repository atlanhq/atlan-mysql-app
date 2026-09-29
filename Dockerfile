# syntax=docker/dockerfile:1
# Base image is overridable so application-sdk PRs can rebuild the connector
# on a PR-scoped runtime base (see the e2e base_image_ref dispatch input).
ARG BASE_IMAGE=registry.atlan.com/public/app-runtime-base:3
FROM ${BASE_IMAGE}

WORKDIR /app

# Copy lock files first for dependency caching
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md ./
# The api/ workspace member (the handler package) is a locked dependency, so
# it must be present for `uv sync --locked` below. Its wheel force-includes the
# contract configmaps from app/generated/, so those come along too.
COPY --chown=appuser:appuser api/ api/
COPY --chown=appuser:appuser app/generated/ app/generated/

# Install dependencies (excluding the project itself) into a new venv
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv venv .venv && \
    uv sync --locked --no-install-project --no-dev

# Copy application code
COPY --chown=appuser:appuser app/ app/

ENV ATLAN_APP_MODULE=app.mysql:MySQLApp
ENV ATLAN_CONTRACT_GENERATED_DIR=/app/app/generated

# Copy Dapr component YAMLs from the installed application-sdk wheel into the
# image. Inlined (rather than `poe download-components`) so the build needs no
# dev tooling — poethepoet stays out of the production image.
RUN uv run python -c "import application_sdk, pathlib, shutil; shutil.copytree(pathlib.Path(application_sdk.__file__).parent / 'components', 'components', dirs_exist_ok=True)"
