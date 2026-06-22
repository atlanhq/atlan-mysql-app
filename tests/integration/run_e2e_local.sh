#!/bin/bash
# Script to run E2E tests locally
# Usage: ./tests/e2e/run_e2e_local.sh

set -e

echo "🚀 Starting E2E Tests for MySQL App"
echo "===================================="

# Check if environment variables are set
if [ -z "$E2E_MYSQL_HOST" ] || [ -z "$E2E_MYSQL_USERNAME" ] || [ -z "$E2E_MYSQL_PASSWORD" ]; then
    echo "❌ Error: Required environment variables not set"
    echo ""
    echo "Please set the following environment variables:"
    echo "  export E2E_MYSQL_HOST=\"your-mysql-host\""
    echo "  export E2E_MYSQL_PORT=\"3306\"  # Optional, defaults to 3306"
    echo "  export E2E_MYSQL_USERNAME=\"your-username\""
    echo "  export E2E_MYSQL_PASSWORD=\"your-password\""
    echo "  export E2E_MYSQL_DATABASE=\"your-database\"  # Optional"
    echo ""
    echo "Or source the setup script:"
    echo "  source tests/e2e/setup_env.sh"
    exit 1
fi

# Set default port if not provided
if [ -z "$E2E_MYSQL_PORT" ]; then
    export E2E_MYSQL_PORT="3306"
fi

# Check if app is running
if ! curl -s http://localhost:8000 > /dev/null 2>&1; then
    echo "⚠️  App server not running on http://localhost:8000"
    echo ""
    echo "Please start the app first:"
    echo "  uv run python main.py &"
    echo "  sleep 20  # Wait for app to start"
    echo ""
    read -p "Do you want to start the app now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Starting app in background..."
        uv run python main.py &
        APP_PID=$!
        echo "App started with PID: $APP_PID"
        echo "Waiting 20 seconds for app to initialize..."
        sleep 20

        # Check if app is now running
        if curl -s http://localhost:8000 > /dev/null 2>&1; then
            echo "✅ App is running"
        else
            echo "❌ App failed to start. Check logs above."
            exit 1
        fi
    else
        echo "Exiting. Please start the app manually and try again."
        exit 1
    fi
else
    echo "✅ App server is running"
fi

# Display test configuration
echo ""
echo "Test Configuration:"
echo "  Host: $E2E_MYSQL_HOST"
echo "  Port: $E2E_MYSQL_PORT"
echo "  Username: $E2E_MYSQL_USERNAME"
if [ -n "$E2E_MYSQL_DATABASE" ]; then
    echo "  Database: $E2E_MYSQL_DATABASE"
else
    echo "  Database: (not specified - optional)"
fi
echo ""

# Run the tests
echo "Running E2E tests..."
echo "===================="
uv run coverage run -m pytest tests/e2e --capture=no --log-cli-level=INFO -v --full-trace

echo ""
echo "✅ E2E tests completed"
