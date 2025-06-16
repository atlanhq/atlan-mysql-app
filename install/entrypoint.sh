#!/bin/bash
set -e

LOG_FILE="/var/log/entrypoint.log"
exec > >(tee -a $LOG_FILE) 2>&1

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $@"
}

error() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $@" >&2
    exit 1
}

log "Entrypoint execution started."

echo "Starting Supervisor with the following ports:"
echo "DAPR_APP_PORT=${ATLAN_DAPR_APP_PORT}"
echo "DAPR_HTTP_PORT=${ATLAN_DAPR_HTTP_PORT}"
echo "DAPR_GRPC_PORT=${ATLAN_DAPR_GRPC_PORT}"
echo "DAPR_METRICS_PORT=${ATLAN_DAPR_METRICS_PORT}"
echo "APP_HTTP_PORT=${ATLAN_APP_HTTP_PORT}"
echo "APP_HTTP_HOST=${ATLAN_APP_HTTP_HOST}"

# Create necessary directories
log "Creating necessary directories for logs and supervisor configurations..."
mkdir -p /var/log/supervisor /var/log/dapr /var/log/app || error "Failed to create necessary directories."

# Initialize Dapr
log "Initializing Dapr runtime and dashboard..."
if ! dapr init --slim --runtime-version=1.14.4 --dashboard-version=0.15.0; then
    error "Failed to initialize Dapr."
fi
log "Dapr initialized successfully."

# Find the correct location of supervisord
log "Locating the supervisord binary..."
SUPERVISORD_PATH=$(which supervisord) || error "Failed to find supervisord binary."

if [[ -z "$SUPERVISORD_PATH" ]]; then
    error "Supervisord binary not found. Please ensure it is installed."
fi
log "Supervisord binary found at $SUPERVISORD_PATH."

log "Activating virtual environment..."
source .venv/bin/activate

# Start Supervisor to manage all processes
log "Starting supervisord with configuration file /etc/supervisor/conf.d/supervisord.conf..."
exec "$SUPERVISORD_PATH" -c /etc/supervisor/conf.d/supervisord.conf || error "Failed to start supervisord."

# Final log entry
log "Entrypoint execution completed successfully."
