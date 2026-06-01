#!/bin/bash
# E2E Test Environment Variables Setup
# Source this file: source tests/e2e/setup_env.sh
#
# For local testing, set these environment variables before sourcing this file:
#   export E2E_MYSQL_HOST="your-host"
#   export E2E_MYSQL_PORT="3306"
#   export E2E_MYSQL_USERNAME="your-username"
#   export E2E_MYSQL_PASSWORD="your-password"
#   export E2E_MYSQL_DATABASE="your-database"
#
# Or create a .env file in the project root and source it before this script.

# Basic Auth - E2E Test Credentials
# Use environment variables if set, otherwise show error
if [ -z "$E2E_MYSQL_HOST" ]; then
    echo "❌ Error: E2E_MYSQL_HOST not set"
    echo "   Please set E2E_MYSQL_HOST environment variable before running tests"
    exit 1
fi

if [ -z "$E2E_MYSQL_PORT" ]; then
    export E2E_MYSQL_PORT="3306"  # Default MySQL port
fi

if [ -z "$E2E_MYSQL_USERNAME" ]; then
    echo "❌ Error: E2E_MYSQL_USERNAME not set"
    echo "   Please set E2E_MYSQL_USERNAME environment variable before running tests"
    exit 1
fi

if [ -z "$E2E_MYSQL_PASSWORD" ]; then
    echo "❌ Error: E2E_MYSQL_PASSWORD not set"
    echo "   Please set E2E_MYSQL_PASSWORD environment variable before running tests"
    exit 1
fi

# Database is optional (can be empty)
if [ -z "$E2E_MYSQL_DATABASE" ]; then
    echo "ℹ️  E2E_MYSQL_DATABASE not set (optional - database will be omitted from connection)"
fi

# Export variables (they may already be set, but ensure they're exported)
export E2E_MYSQL_HOST
export E2E_MYSQL_PORT
export E2E_MYSQL_USERNAME
export E2E_MYSQL_PASSWORD
# Export database only if set
if [ -n "$E2E_MYSQL_DATABASE" ]; then
    export E2E_MYSQL_DATABASE
fi

echo "✅ E2E test environment variables set"
if [ -n "$E2E_MYSQL_DATABASE" ]; then
    echo "   Basic Auth: $E2E_MYSQL_USERNAME@$E2E_MYSQL_HOST:$E2E_MYSQL_PORT/$E2E_MYSQL_DATABASE"
else
    echo "   Basic Auth: $E2E_MYSQL_USERNAME@$E2E_MYSQL_HOST:$E2E_MYSQL_PORT (no database specified)"
fi
