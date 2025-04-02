from application_sdk.transformers.common.utils import build_atlas_qualified_name

from app.transformers.atlas import MySQLColumn


def test_mysql_column_transformer():
    # Test data
    raw_data = {
        "column_name": "id",
        "table_name": "users",
        "table_schema": "public",
        "table_catalog": "test_db",
        "data_type": "int",
        "character_maximum_length": None,
        "is_nullable": "NO",
        "column_default": "nextval('users_id_seq'::regclass)",
        "primary_key": "YES",
        "foreign_key": "NO",
        "constraint_name": "users_pkey",
        "character_set_name": "utf8mb4",
        "collation_name": "utf8mb4_unicode_ci",
        "column_size": 4,
        "decimal_digits": 0,
        "connection_qualified_name": "default/mysql/1234",
        "ordinal_position": 1,
    }

    # Get attributes using the class method
    result = MySQLColumn.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "id"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "users", "id"
    )
    assert attributes["data_type"] == "int"
    assert attributes["is_nullable"] is False
    assert attributes["is_primary"] is True
    assert attributes["is_foreign"] is False
    assert attributes["description"] == "Primary key column"
    assert attributes["column_default"] == "nextval('users_id_seq'::regclass)"
    assert custom_attributes["characterSet"] == "utf8mb4"
    assert custom_attributes["collation"] == "utf8mb4_unicode_ci"


def test_mysql_column_transformer_foreign_key():
    # Test data for foreign key column
    raw_data = {
        "column_name": "user_id",
        "table_name": "orders",
        "table_schema": "public",
        "table_catalog": "test_db",
        "data_type": "int",
        "is_nullable": "NO",
        "primary_key": "NO",
        "foreign_key": "YES",
        "constraint_name": "orders_user_id_fkey",
        "fk_schema": "public",
        "fk_table": "users",
        "fk_column": "id",
        "connection_qualified_name": "default/mysql/1234",
        "ordinal_position": 1,
    }

    # Get attributes using the class method
    result = MySQLColumn.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "user_id"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "orders", "user_id"
    )
    assert attributes["is_primary"] is False
    assert attributes["is_foreign"] is True
    assert attributes["description"] == "Foreign key column"
    assert custom_attributes["referencedSchema"] == "public"
    assert custom_attributes["referencedTable"] == "users"
    assert custom_attributes["referencedColumn"] == "id"


def test_mysql_column_transformer_nullable():
    # Test data for nullable column
    raw_data = {
        "column_name": "email",
        "table_name": "users",
        "table_schema": "public",
        "table_catalog": "test_db",
        "data_type": "varchar",
        "character_maximum_length": 255,
        "is_nullable": "YES",
        "primary_key": "NO",
        "foreign_key": "NO",
        "connection_qualified_name": "default/mysql/1234",
        "ordinal_position": 1,
    }

    # Get attributes using the class method
    result = MySQLColumn.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    result["custom_attributes"]

    assert attributes["name"] == "email"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "users", "email"
    )
    assert attributes["is_nullable"] is True
    assert attributes["max_length"] == 255
    assert attributes["is_primary"] is False
    assert attributes["is_foreign"] is False


def test_mysql_column_transformer_missing_fields():
    # Test data with missing fields
    raw_data = {
        "column_name": "name",
        "table_name": "users",
        "table_schema": "public",
        "table_catalog": "test_db",
        "connection_qualified_name": "default/mysql/1234",
        "ordinal_position": 1,
        "data_type": "varchar",  # Required by parent class
    }

    # Get attributes using the class method
    result = MySQLColumn.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    custom_attributes = result["custom_attributes"]

    assert attributes["name"] == "name"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "users", "name"
    )
    assert attributes["is_nullable"] is True  # Default value
    assert attributes["is_primary"] is False  # Default value
    assert attributes["is_foreign"] is False  # Default value
    assert "characterSet" not in custom_attributes
    assert "collation" not in custom_attributes
    assert "referencedSchema" not in custom_attributes
    assert "referencedTable" not in custom_attributes
    assert "referencedColumn" not in custom_attributes


def test_mysql_column_transformer_invalid_data():
    # Test data with invalid values
    raw_data = {
        "column_name": "invalid",
        "table_name": "users",
        "table_schema": "public",
        "table_catalog": "test_db",
        "is_nullable": "INVALID",
        "primary_key": "INVALID",
        "foreign_key": "INVALID",
        "connection_qualified_name": "default/mysql/1234",
        "ordinal_position": 1,
        "data_type": "varchar",  # Required by parent class
    }

    # Get attributes using the class method
    result = MySQLColumn.get_attributes(raw_data)

    # Assertions
    assert result is not None
    assert "attributes" in result
    assert "custom_attributes" in result
    assert "entity_class" in result

    attributes = result["attributes"]
    result["custom_attributes"]

    assert attributes["name"] == "invalid"
    assert attributes["qualified_name"] == build_atlas_qualified_name(
        "default/mysql/1234", "test_db", "public", "users", "invalid"
    )
    assert attributes["is_nullable"] is True  # Default value for invalid
    assert attributes["is_primary"] is False  # Default value for invalid
    assert attributes["is_foreign"] is False  # Default value for invalid
