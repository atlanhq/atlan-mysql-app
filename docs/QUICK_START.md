# Quick Start Guide

This guide will help you get up and running with the MySQL application in no time.

## 1. Clone the Repository

```bash
git clone --recurse-submodules https://github.com/atlanhq/phoenix-mysql-app.git
```

## 2. Install Atlan PaaS CLI
- To install the CLI follow the [README](https://github.com/atlanhq/phoenix-atlan-cli/blob/main/README.md).

## 3. Install the App Dependencies

```bash
patlan app install
```

## 4. Run the App

```bash
patlan app run
```

This command launches your application, making it ready for development and testing.

Open http://localhost:8000/ on your browser to access the application :rocket:

Open http://localhost:8050/workflows on browser to access the application dashboard :computer:

> [!TIP]
> If you want to stop and clean the process, run the below command:

```bash
patlan app stop
```

> [!TIP]
> Head over to the [setup guide](./SETUP_MAC.md) to learn more about manual deployment.

## 5. Verify MySQL Connection

The application will automatically test the MySQL connection on startup. You can verify the connection by:

1. Checking the application logs for successful connection messages
2. Using the system check endpoint: http://localhost:8000/system/check
3. Testing the metadata extraction workflow through the dashboard

## 6. Troubleshooting

If you encounter any issues:

1. **Connection Issues**
   - Verify MySQL server is running
   - Check connection parameters
   - Ensure MySQL user has appropriate permissions
   - Verify network connectivity

2. **Metadata Extraction Issues**
   - Check schema inclusion/exclusion patterns
   - Verify table access permissions
   - Review application logs for specific errors

3. **Performance Issues**
   - Adjust connection pool settings
   - Review MySQL server configuration
   - Check network latency
