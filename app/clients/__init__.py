import os
from urllib.parse import quote_plus

from application_sdk.clients.sql import SQLClient
from application_sdk.common.aws_utils import (
    generate_aws_rds_token_with_iam_role,
    generate_aws_rds_token_with_iam_user,
)

from utils.utils import parse_credentials_extra


class MySQLClient(SQLClient):
    """MySQL client implementation for database connections.

    This class extends SQLClient to provide MySQL-specific connection functionality.
    """

    def get_iam_user_connection_string(self):
        """Generate connection string for IAM user authentication."""
        extra = parse_credentials_extra(self.credentials)
        aws_access_key_id = self.credentials["username"]
        aws_secret_access_key = self.credentials["password"]
        host = self.credentials["host"]
        user = extra.get("username")
        # database = extra.get("database")
        if not user:
            raise ValueError("username is required for IAM user authentication")
        # if not database:
        #     raise ValueError("database is required for IAM user authentication")

        port = self.credentials.get("port", 3306)
        region = self.credentials.get("region", None)
        token = quote_plus(
            generate_aws_rds_token_with_iam_user(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                host=host,
                user=user,
                port=port,
                region=region,
            )
        )

        return f"mysql+pymysql://{user}:{token}@{host}:{port}"

    def get_iam_role_connection_string(self):
        """Generate connection string for IAM role authentication."""
        extra = parse_credentials_extra(self.credentials)
        aws_role_arn = extra.get("aws_role_arn")
        # database = extra.get("database")
        external_id = extra.get("aws_external_id")
        if not aws_role_arn:
            raise ValueError("aws_role_arn is required for IAM role authentication")
        # if not database:
        #     raise ValueError("database is required for IAM role authentication")
        if not external_id:
            raise ValueError("aws_external_id is required for IAM role authentication")
        session_name = os.getenv("AWS_SESSION_NAME", "temp-session")
        username = self.credentials["username"]
        host = self.credentials["host"]
        port = self.credentials.get("port", 3306)
        region = self.credentials.get("region", None)
        token = quote_plus(
            generate_aws_rds_token_with_iam_role(
                role_arn=aws_role_arn,
                host=host,
                user=username,
                external_id=external_id,
                session_name=session_name,
                port=port,
                region=region,
            )
        )
        return f"mysql+pymysql://{username}:{token}@{host}:{port}"

    def get_basic_connection_string(self):
        """Generate connection string for basic authentication."""
        # extra = parse_credentials_extra(self.credentials)
        username = self.credentials["username"]
        password = self.credentials["password"]
        host = self.credentials["host"]
        port = self.credentials.get("port", 3306)
        # database = extra.get("database")
        # if not database:
        #     raise ValueError("database is required for basic authentication")
        encoded_password: str = quote_plus(password)
        return f"mysql+pymysql://{username}:{encoded_password}@{host}:{port}"

    def get_sqlalchemy_connection_string(self) -> str:
        """Get SQLAlchemy connection string based on the auth type."""
        authType = self.credentials.get("authType", "basic")  # Default to basic auth

        connection_string = ""

        match authType:
            case "iam_user":
                connection_string = self.get_iam_user_connection_string()
            case "iam_role":
                connection_string = self.get_iam_role_connection_string()
            case "basic":
                connection_string = self.get_basic_connection_string()
            case _:
                raise ValueError(f"Invalid auth type: {authType}")

        return connection_string
