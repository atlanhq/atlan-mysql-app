# syntax=docker/dockerfile:1
# Base image is overridable so application-sdk PRs can rebuild the connector
# on a PR-scoped runtime base (see the e2e base_image_ref dispatch input).
ARG BASE_IMAGE=registry.atlan.com/public/app-runtime-base:3
FROM ${BASE_IMAGE}

WORKDIR /app

# Copy lock files first for dependency caching
COPY --chown=appuser:appuser pyproject.toml uv.lock README.md ./

# Install dependencies (excluding the project itself) into a new venv.
# Private git dep (query-redaction): GitHub remotes are rewritten to token https
# from a BuildKit secret, removed in-layer; its LFS jar is not needed.
RUN --mount=type=secret,id=git_token,uid=1000 \
    --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    git config --global url."https://x-access-token:$(cat /run/secrets/git_token)@github.com/".insteadOf "ssh://git@github.com/" && \
    git config --global --add url."https://x-access-token:$(cat /run/secrets/git_token)@github.com/".insteadOf "https://github.com/" && \
    uv venv .venv && \
    GIT_LFS_SKIP_SMUDGE=1 uv sync --locked --no-install-project --no-dev && \
    rm -f "$HOME/.gitconfig"

# Copy application code
COPY --chown=appuser:appuser app/ app/

ENV ATLAN_APP_MODULE=app.mysql:MySQLApp
ENV ATLAN_CONTRACT_GENERATED_DIR=/app/app/generated

# Copy Dapr component YAMLs from the installed application-sdk wheel into the
# image. Inlined (rather than `poe download-components`) so the build needs no
# dev tooling — poethepoet stays out of the production image.
RUN uv run python -c "import application_sdk, pathlib, shutil; shutil.copytree(pathlib.Path(application_sdk.__file__).parent / 'components', 'components', dirs_exist_ok=True)"
