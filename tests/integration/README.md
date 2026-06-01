# E2E Tests for MySQL App

This directory contains end-to-end (E2E) tests for the MySQL metadata extraction app.

## Required Environment Variables

The E2E tests require the following environment variables to be set:

### Required Variables

- **`E2E_MYSQL_HOST`**: MySQL server hostname or IP address
- **`E2E_MYSQL_PORT`**: MySQL server port (default: `3306`)
- **`E2E_MYSQL_USERNAME`**: MySQL username for authentication
- **`E2E_MYSQL_PASSWORD`**: MySQL password for authentication
- **`E2E_MYSQL_DATABASE`**: MySQL database name to use for testing

### Optional Variables

- **`ATLAN_SQL_SERVER_MIN_VERSION`**: Minimum MySQL version required (default: `8.0`)

## Setting Up Environment Variables

### Method 1: Using setup_env.sh (Recommended for Local Testing)

1. Set the environment variables:
   ```bash
   export E2E_MYSQL_HOST="your-mysql-host"
   export E2E_MYSQL_PORT="3306"
   export E2E_MYSQL_USERNAME="your-username"
   export E2E_MYSQL_PASSWORD="your-password"
   export E2E_MYSQL_DATABASE="your-database"
   ```

2. Source the setup script:
   ```bash
   source tests/e2e/setup_env.sh
   ```

### Method 2: Using .env File

1. Create a `.env` file in the project root:
   ```bash
   cd /path/to/atlan-mysql-app
   touch .env
   ```

2. Add your credentials to `.env`:
   ```bash
   E2E_MYSQL_HOST=your-mysql-host
   E2E_MYSQL_PORT=3306
   E2E_MYSQL_USERNAME=your-username
   E2E_MYSQL_PASSWORD=your-password
   E2E_MYSQL_DATABASE=your-database
   ATLAN_SQL_SERVER_MIN_VERSION=8.0
   ```

3. Source the .env file:
   ```bash
   # Using bash
   set -a; source .env; set +a

   # Or export manually
   export $(cat .env | xargs)
   ```

### Method 3: Export Directly in Shell

```bash
export E2E_MYSQL_HOST="your-mysql-host"
export E2E_MYSQL_PORT="3306"
export E2E_MYSQL_USERNAME="your-username"
export E2E_MYSQL_PASSWORD="your-password"
export E2E_MYSQL_DATABASE="your-database"
export ATLAN_SQL_SERVER_MIN_VERSION="8.0"
```

## Running E2E Tests

### Prerequisites

1. Ensure the MySQL app is running:
   ```bash
   uv run scalene --profile-all --cli --outfile ./.github/scalene.json --json main.py &
   sleep 20  # Wait for app to start
   ```

2. Set environment variables (see above)

3. Ensure you have access to a MySQL database with test data

### Run All E2E Tests

```bash
uv run coverage run -m pytest tests/e2e -v
```

### Run Specific Test

```bash
uv run coverage run -m pytest tests/e2e/test_mysql_workflow/test_mysql_workflow.py -v
```

### Run with Detailed Output

```bash
uv run coverage run -m pytest tests/e2e --capture=no --log-cli-level=INFO -v --full-trace
```

## Test Structure

The E2E tests follow this order:

1. **`test_health_check`**: Verifies the server is running
2. **`test_auth`**: Tests authentication with MySQL credentials
3. **`test_metadata`**: Tests metadata retrieval from MySQL
4. **`test_preflight_check`**: Tests preflight checks (database schema, tables, version)
5. **`test_run_workflow`**: Runs the full metadata extraction workflow
6. **`test_configuration_get`**: Tests configuration retrieval
7. **`test_data_validation`**: Validates extracted data (optional)

## GitHub Actions / CI/CD

For CI/CD pipelines, set these as GitHub Secrets. The secret names match the environment variable names for consistency.

### Required GitHub Secrets

Set these secrets in your GitHub repository settings (Settings → Secrets and variables → Actions):

- **`E2E_MYSQL_HOST`** - MySQL server hostname
- **`E2E_MYSQL_USERNAME`** - MySQL username
- **`E2E_MYSQL_PASSWORD`** - MySQL password
- **`E2E_MYSQL_DATABASE`** - MySQL database name

### Optional Configuration

- **`E2E_MYSQL_PORT`** - Can be hardcoded to `3306` in the workflow (default MySQL port)
- **`ATLAN_SQL_SERVER_MIN_VERSION`** - Can be hardcoded to `"8.0"` in the workflow

### Example GitHub Actions Workflow Configuration

The workflow uses these secrets as shown below:

```yaml
env:
  E2E_MYSQL_HOST: ${{ secrets.E2E_MYSQL_HOST }}
  E2E_MYSQL_PORT: 3306
  E2E_MYSQL_USERNAME: ${{ secrets.E2E_MYSQL_USERNAME }}
  E2E_MYSQL_PASSWORD: ${{ secrets.E2E_MYSQL_PASSWORD }}
  E2E_MYSQL_DATABASE: ${{ secrets.E2E_MYSQL_DATABASE }}
  ATLAN_SQL_SERVER_MIN_VERSION: "8.0"
```

**Note**: The GitHub secret names match the environment variable names exactly (e.g., `E2E_MYSQL_HOST` secret → `E2E_MYSQL_HOST` env var), making it easy to remember and maintain.

## Troubleshooting

### Connection Errors

- Verify MySQL server is accessible from your machine
- Check firewall rules allow connections on the specified port
- Verify credentials are correct
- Test connection manually: `mysql -h $E2E_MYSQL_HOST -P $E2E_MYSQL_PORT -u $E2E_MYSQL_USERNAME -p$E2E_MYSQL_PASSWORD`

### Test Failures

- Check application logs for detailed error messages
- Verify the test database has the expected schema and data
- Ensure the app server is running before executing tests
- Check Temporal workflow status if workflow tests fail

### Environment Variable Issues

- Use `echo $E2E_MYSQL_HOST` to verify variables are set
- Ensure variables are exported (not just set in current shell)
- Check for typos in variable names
