# Builder stage
FROM registry.access.redhat.com/ubi8/ubi-minimal AS builder

ARG TARGETARCH

ENV PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache/$TARGETARCH \
    POETRY_VERSION=1.8.5

# Install OS build dependencies
RUN microdnf upgrade -y && \
    microdnf install -y \
    git \
    openssh-clients \
    gcc \
    gcc-c++ \
    make \
    python3.12-devel \
    openssl-devel \
    bzip2-devel \
    libffi-devel \
    zlib-devel \
    wget \
    findutils \
    && microdnf clean all

# Install Python 3.12 and pip 3.12
RUN microdnf install -y python3.12 python3.12-pip && \
    microdnf clean all

# Create symlink for python3 to point to python3.12
RUN ln -s /usr/bin/python3.12 /usr/local/bin/python && \
    ln -s /usr/bin/pip3.12 /usr/local/bin/pip

# Upgrade pip and install Poetry
RUN pip install --upgrade pip && \
    pip install "poetry==$POETRY_VERSION"

# Use the secret during build
RUN --mount=type=secret,id=PRIVATE_REPO_ACCESS_TOKEN \
    export PRIVATE_REPO_ACCESS_TOKEN=$(cat /run/secrets/PRIVATE_REPO_ACCESS_TOKEN) && \
    if [ ! -z "$PRIVATE_REPO_ACCESS_TOKEN" ]; then \
        git config --global url."https://${PRIVATE_REPO_ACCESS_TOKEN}@github.com/".insteadOf "git@github.com:"; \
    fi

WORKDIR /application

# Install Python dependencies
COPY ./pyproject.toml ./poetry.lock ./

# The cache directory makes rebuilding a docker image if pyproject.toml changes near instant
RUN --mount=type=cache,target=$POETRY_CACHE_DIR poetry install --no-root --without dev,test --no-interaction --no-ansi

# Runtime Stage
FROM registry.access.redhat.com/ubi8/ubi-minimal AS runtime

WORKDIR /application

# Set environment for virtual environment
ENV VIRTUAL_ENV=/application/.venv \
    PATH="/application/.venv/bin:$PATH"

# Copy the virtual environment from the builder
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# Enable AppStream repository and install Python and other necessary runtime packages
RUN microdnf upgrade -y && \
    microdnf install -y \
    python3.12 \
    && microdnf clean all

# Create symlink for python3 to point to python3.12
RUN ln -s /usr/bin/python3.12 /usr/local/bin/python

# Copy the rest of the code
COPY . /application

# Set the entrypoint
ENTRYPOINT ["python", "/application/main.py"]
