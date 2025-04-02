from application_sdk.transformers.common.utils import build_atlas_qualified_name

from app.transformers.atlas import MySQLTable


def test_mysql_table_transformer():
    # Test data
    raw_data = {
        "table_name": "users",
        "table_schema": "public",
        "table_catalog": "test_db",
        "table_type": "BASE TABLE",
        "row_count": 1000,
        "data_length": 1024000,
        "description": "User information table",
        "create_time": "2024-01-01 00:00:00",
        "update_time": "2024-01-02 00:00:00",
        "engine": "InnoDB",
        "row_format": "Dynamic",
        "table_collation": "utf8mb4_unicode_ci",
        "connection_qualified_name": "default/mysql/1234",
    }

    # Get attributes using the class method
    result = MySQLTable.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "users"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "users"
    )
    assert attributes["row_count"] == 1000
    assert attributes["size_bytes"] == 1024000
    assert attributes["is_partitioned"] is False
    assert custom_attributes["createTime"] == "2024-01-01 00:00:00"
    assert custom_attributes["updateTime"] == "2024-01-02 00:00:00"
    assert custom_attributes["engine"] == "InnoDB"
    assert custom_attributes["rowFormat"] == "Dynamic"
    assert custom_attributes["collation"] == "utf8mb4_unicode_ci"
    assert custom_attributes["table_type"] == "BASE TABLE"


def test_mysql_table_transformer_partitioned():
    # Test data for partitioned table
    raw_data = {
        "table_name": "orders",
        "table_schema": "public",
        "table_catalog": "test_db",
        "table_type": "PARTITIONED TABLE",
        "is_partition": "true",
        "partition_strategy": "RANGE",
        "partition_count": 4,
        "partition_constraint": "PARTITION BY RANGE (created_at)",
        "row_count": 5000,
        "data_length": 5120000,
        "description": "Order information table",
        "connection_qualified_name": "default/mysql/1234",
    }

    # Get attributes using the class method
    result = MySQLTable.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "orders"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "orders"
    )
    assert attributes["row_count"] == 5000
    assert attributes["size_bytes"] == 5120000
    assert attributes["is_partitioned"] is True
    assert attributes["partition_strategy"] == "RANGE"
    assert attributes["partition_count"] == 4
    assert attributes["constraint"] == "PARTITION BY RANGE (created_at)"
    assert custom_attributes["table_type"] == "PARTITIONED TABLE"


def test_mysql_table_transformer_missing_fields():
    # Test data with missing fields
    raw_data = {
        "table_name": "products",
        "table_schema": "public",
        "table_catalog": "test_db",
        "connection_qualified_name": "default/mysql/1234",
    }

    # Get attributes using the class method
    result = MySQLTable.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "products"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "products"
    )
    assert attributes["row_count"] == 0  # Default value
    assert attributes["size_bytes"] == 0  # Default value
    assert attributes["is_partitioned"] is False  # Default value
    assert "createTime" not in custom_attributes
    assert "updateTime" not in custom_attributes
    assert "rowFormat" not in custom_attributes
    assert "collation" not in custom_attributes
    assert custom_attributes["table_type"] == "TABLE"  # Default value


def test_mysql_table_transformer_invalid_data():
    # Test data with invalid values
    raw_data = {
        "table_name": "invalid",
        "table_schema": "public",
        "table_catalog": "test_db",
        "table_type": "INVALID_TYPE",
        "is_partition": "INVALID",
        "connection_qualified_name": "default/mysql/1234",
    }

    # Get attributes using the class method
    result = MySQLTable.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "invalid"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "invalid"
    )
    assert attributes["row_count"] == 0  # Default value
    assert attributes["size_bytes"] == 0  # Default value
    assert attributes["is_partitioned"] is False  # Default value for invalid
    assert custom_attributes["table_type"] == "INVALID_TYPE"  # Preserved as is
