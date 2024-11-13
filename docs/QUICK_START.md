# Quick Start Guide

This guide will help you get up and running with the application in no time.

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
