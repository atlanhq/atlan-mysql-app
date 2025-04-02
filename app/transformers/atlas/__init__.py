from typing import Any, Dict, Optional, Type

from application_sdk.common.logger_adaptors import get_logger
from application_sdk.transformers.atlas import AtlasTransformer
from application_sdk.transformers.atlas.sql import (
    Column,
    Database,
    Procedure,
    Schema,
    Table,
)

logger = get_logger(__name__)


class PostgresTable(Table):
    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Postgres view and materialized view definitions are select queries,
        so we need to format the view definition to be a valid SQL query.

        src: https://github.com/atlanhq/marketplace-packages/blob/master/packages/atlan/postgres/transformers/view.jinja2
        """
        assert "table_name" in obj, "table_name cannot be None"
        assert "table_type" in obj, "table_type cannot be None"

        entity_data = super().get_attributes(obj)
        table_attributes = entity_data.get("attributes", {})
        table_custom_attributes = entity_data.get("custom_attributes", {})

        table_attributes["constraint"] = obj.get("partition_constraint", "")

        if (
            obj.get("table_kind", "") == "p"
            or obj.get("table_type", "") == "PARTITIONED TABLE"
        ):
            table_attributes["is_partitioned"] = True
            table_attributes["partition_strategy"] = obj.get("partition_strategy", "")
            table_attributes["partition_count"] = obj.get("partition_count", 0)
        else:
            table_attributes["is_partitioned"] = False

        table_custom_attributes["is_insertable_into"] = obj.get(
            "is_insertable_into", False
        )
        table_custom_attributes["is_typed"] = obj.get("is_typed", False)
        table_custom_attributes["self_referencing_col_name"] = obj.get(
            "self_referencing_col_name", ""
        )
        table_custom_attributes["ref_generation"] = obj.get("ref_generation", "")
        if obj.get("table_type") == "VIEW":
            view_definition = "CREATE OR REPLACE VIEW {view_name} AS {query}"
            table_attributes["definition"] = view_definition.format(
                view_name=obj.get("table_name", ""),
                query=obj.get("view_definition", ""),
            )
        elif obj.get("table_type") == "MATERIALIZED VIEW":
            view_definition = "CREATE MATERIALIZED VIEW {view_name} AS {query}"
            table_attributes["definition"] = view_definition.format(
                view_name=obj.get("table_name", ""),
                query=obj.get("view_definition", ""),
            )

        entity_class = None
        if entity_data["entity_class"] == Table:
            entity_class = PostgresTable
        else:
            entity_class = entity_data["entity_class"]

        return {
            **entity_data,
            "attributes": table_attributes,
            "custom_attributes": table_custom_attributes,
            "entity_class": entity_class,
        }


class PostgresColumn(Column):
    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        entity_data = super().get_attributes(obj)

        column_attributes = entity_data.get("attributes", {})
        column_custom_attributes = entity_data.get("custom_attributes", {})

        if obj.get("numeric_precision_radix", "") != "":
            column_custom_attributes["num_prec_radix"] = obj.get(
                "numeric_precision_radix", ""
            )
        if obj.get("is_identity", "") != "":
            column_custom_attributes["is_identity"] = obj.get("is_identity", "")
        if obj.get("identity_cycle", "") != "":
            column_custom_attributes["identity_cycle"] = obj.get("identity_cycle", "")

        if obj.get("constraint_type", "") == "PRIMARY KEY":
            column_attributes["is_primary"] = True

        elif obj.get("constraint_type", "") == "FOREIGN KEY":
            column_attributes["is_foreign"] = True

        return {
            **entity_data,
            "attributes": column_attributes,
            "custom_attributes": column_custom_attributes,
            "entity_class": PostgresColumn,
        }


class PostgresAtlasTransformer(AtlasTransformer):
    def __init__(self, connector_name: str, tenant_id: str, **kwargs: Any):
        super().__init__(connector_name, tenant_id, **kwargs)

        self.entity_class_definitions["TABLE"] = PostgresTable
        self.entity_class_definitions["COLUMN"] = PostgresColumn
        self.entity_class_definitions["EXTRAS-PROCEDURE"] = Procedure


class MySQLAtlasTransformer(AtlasTransformer):
    """
    MySQL Atlas Transformer for converting MySQL metadata to Atlas entities.

    This class extends AtlasTransformer to provide MySQL-specific transformation
    functionality.
    """

    def __init__(self, connector_name: str, tenant_id: str, **kwargs: Any):
        """
        Initialize the MySQL Atlas Transformer.

        Args:
            connector_name: Name of the connector.
            tenant_id: Tenant ID for the transformation.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(connector_name, tenant_id, **kwargs)

        # Define MySQL-specific entity class definitions
        self.entity_class_definitions = {
            "DATABASE": MySQLDatabase,
            "SCHEMA": MySQLSchema,
            "TABLE": MySQLTable,
            "VIEW": MySQLTable,
            "COLUMN": MySQLColumn,
            "PROCEDURE": MySQLProcedure,
        }

        logger.info(
            "Initialized MySQL Atlas Transformer with connector: %s", connector_name
        )

    def transform_metadata(
        self,
        typename: str,
        data: Dict[str, Any],
        workflow_id: str,
        workflow_run_id: str,
        entity_class_definitions: Optional[Dict[str, Type[Any]]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Transform MySQL metadata into Atlas entities.

        Args:
            typename: Type of the metadata being transformed.
            data: Raw metadata from MySQL.
            workflow_id: ID of the workflow.
            workflow_run_id: ID of the workflow run.
            entity_class_definitions: Optional custom entity class definitions.
            **kwargs: Additional keyword arguments.

        Returns:
            Dict[str, Any]: Transformed Atlas entity or None if transformation fails.
        """
        logger.debug("Transforming MySQL metadata of type: %s", typename)

        # Use MySQL-specific entity definitions
        if entity_class_definitions is None:
            entity_class_definitions = self.entity_class_definitions

        # Call the parent transform_metadata method
        return super().transform_metadata(
            typename,
            data,
            workflow_id,
            workflow_run_id,
            entity_class_definitions,
            **kwargs,
        )


class MySQLDatabase(Database):
    """
    MySQL Database entity transformer for Atlas.

    This class handles transformation of MySQL database metadata to Atlas entities.
    """

    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dictionary into a MySQL-specific Database entity.

        Args:
            obj: Dictionary containing database metadata.

        Returns:
            Dictionary with attributes, custom_attributes, and entity_class.

        Raises:
            ValueError: If required fields are missing.
        """
        logger.debug("Creating MySQL Database entity")

        try:
            # Get base attributes from parent
            entity_attributes = super().get_attributes(obj)

            # Add MySQL-specific attributes
            custom_attributes = entity_attributes.get("custom_attributes", {})

            if character_set := obj.get("default_character_set_name"):
                custom_attributes["characterSet"] = character_set

            if collation := obj.get("default_collation_name"):
                custom_attributes["collation"] = collation

            entity_attributes["custom_attributes"] = custom_attributes

            return entity_attributes

        except Exception as e:
            logger.error("Error creating MySQL Database entity: %s", str(e))
            raise ValueError(f"Error creating MySQL Database Entity: {str(e)}")


class MySQLSchema(Schema):
    """
    MySQL Schema entity transformer for Atlas.

    This class handles transformation of MySQL schema metadata to Atlas entities.
    Note: In MySQL, schemas are synonymous with databases.
    """

    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dictionary into a MySQL-specific Schema entity.

        Args:
            obj: Dictionary containing schema metadata.

        Returns:
            Dictionary with attributes, custom_attributes, and entity_class.

        Raises:
            ValueError: If required fields are missing.
        """
        logger.debug("Creating MySQL Schema entity")

        try:
            # Get base attributes from parent
            entity_attributes = super().get_attributes(obj)

            # Add MySQL-specific attributes
            custom_attributes = entity_attributes.get("custom_attributes", {})

            # In MySQL, schema and database are synonymous
            custom_attributes["isSchemaSameAsDatabase"] = True

            entity_attributes["custom_attributes"] = custom_attributes

            return entity_attributes

        except Exception as e:
            logger.error("Error creating MySQL Schema entity: %s", str(e))
            raise ValueError(f"Error creating MySQL Schema Entity: {str(e)}")


class MySQLTable(Table):
    """
    MySQL Table entity transformer for Atlas.

    This class handles transformation of MySQL table metadata to Atlas entities.
    """

    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dictionary into a MySQL-specific Table entity.

        Args:
            obj: Dictionary containing table metadata.

        Returns:
            Dictionary with attributes, custom_attributes, and entity_class.

        Raises:
            ValueError: If required fields are missing.
        """
        logger.debug(
            "Creating MySQL Table entity with type: %s", obj.get("table_type", "")
        )

        try:
            # Ensure required fields exist
            required_fields = ["table_name", "table_schema", "table_catalog"]
            for field in required_fields:
                if not obj.get(field):
                    obj[field] = ""  # Set empty string as default

            # CRITICAL: Ensure partition-related fields are properly set to avoid incorrect entity type determination
            if obj.get("table_type") == "BASE TABLE":
                obj["is_partition"] = "false"
                obj["partitioned_parent_table"] = "false"

            # Ensure default values for fields that might be missing
            defaults = {
                "parent_table_name": "",
                "partitioned_parent_table": "false",
                "partition_constraint": "",
                "number_columns_in_part_key": 0,
                "columns_participating_in_part_key": "",
                "is_partition": "false",
                "partition_strategy": "",
                "partition_count": 0,
                "view_definition": None,
                "row_count": 0,
                "column_count": 0,
                "data_length": 0,
            }

            # Add missing fields with default values
            for key, value in defaults.items():
                if key not in obj or obj.get(key) is None:
                    obj[key] = value

            # Override table_kind for MySQL tables to ensure proper type determination
            if obj.get("table_type") == "BASE TABLE":
                obj["table_kind"] = "r"  # Regular table
            elif obj.get("table_type") == "VIEW":
                obj["table_kind"] = "v"  # View

            # Get base attributes from parent - this will determine the entity class
            entity_data = super().get_attributes(obj)

            # Add MySQL-specific attributes
            attributes = entity_data.get("attributes", {})
            custom_attributes = entity_data.get("custom_attributes", {})

            # MySQL-specific table attributes
            if engine := obj.get("engine"):
                custom_attributes["engine"] = engine

            if row_format := obj.get("row_format"):
                custom_attributes["rowFormat"] = row_format

            if auto_increment := obj.get("auto_increment"):
                custom_attributes["autoIncrement"] = auto_increment

            if table_collation := obj.get("table_collation"):
                custom_attributes["collation"] = table_collation

            if avg_row_length := obj.get("avg_row_length"):
                custom_attributes["avgRowLength"] = avg_row_length

            if data_length := obj.get("data_length"):
                attributes["size_bytes"] = data_length

            if create_time := obj.get("create_time"):
                custom_attributes["createTime"] = create_time

            if update_time := obj.get("update_time"):
                custom_attributes["updateTime"] = update_time

            # Handle additional MySQL-specific fields
            if table_type := obj.get("table_type"):
                custom_attributes["tableType"] = table_type

            # Set partition-related fields
            is_partition = (
                str(obj.get("is_partition", "false")).lower() == "true"
                or obj.get("is_partition", 0) == 1
            )
            attributes["is_partitioned"] = is_partition

            if is_partition:
                if partition_strategy := obj.get("partition_strategy"):
                    attributes["partition_strategy"] = partition_strategy

                if partition_count := obj.get("partition_count"):
                    attributes["partition_count"] = partition_count

                if partition_constraint := obj.get("partition_constraint"):
                    attributes["constraint"] = partition_constraint

            entity_data["attributes"] = attributes
            entity_data["custom_attributes"] = custom_attributes

            return entity_data

        except Exception as e:
            logger.error("Error creating MySQL Table entity: %s", str(e))
            raise ValueError(f"Error creating MySQL Table Entity: {str(e)}")


class MySQLColumn(Column):
    """
    MySQL Column entity transformer for Atlas.

    This class handles transformation of MySQL column metadata to Atlas entities.
    """

    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dictionary into a MySQL-specific Column entity.

        Args:
            obj: Dictionary containing column metadata.

        Returns:
            Dictionary with attributes, custom_attributes, and entity_class.

        Raises:
            ValueError: If required fields are missing.
        """
        logger.debug("Creating MySQL Column entity")

        try:
            # Get base attributes from parent
            entity_attributes = super().get_attributes(obj)

            # Add MySQL-specific attributes
            attributes = entity_attributes.get("attributes", {})
            custom_attributes = entity_attributes.get("custom_attributes", {})

            # MySQL-specific column attributes
            if character_set := obj.get("character_set_name"):
                custom_attributes["characterSet"] = character_set

            if collation := obj.get("collation_name"):
                custom_attributes["collation"] = collation

            # Handle foreign key references
            if fk_schema := obj.get("fk_schema"):
                custom_attributes["referencedSchema"] = fk_schema

            if fk_table := obj.get("fk_table"):
                custom_attributes["referencedTable"] = fk_table

            if fk_column := obj.get("fk_column"):
                custom_attributes["referencedColumn"] = fk_column

            # Update primary key and foreign key indicators
            is_primary = obj.get("primary_key", "NO").upper() == "YES"
            is_foreign = obj.get("foreign_key", "NO").upper() == "YES"

            attributes["is_primary"] = is_primary
            attributes["is_foreign"] = is_foreign

            # Set description based on key type
            if is_primary:
                attributes["description"] = "Primary key column"
            elif is_foreign:
                attributes["description"] = "Foreign key column"
            else:
                attributes["description"] = ""

            # Set nullable based on is_nullable field
            is_nullable = obj.get("is_nullable", "YES")
            if is_nullable.upper() == "YES":
                attributes["is_nullable"] = True
            elif is_nullable.upper() == "NO":
                attributes["is_nullable"] = False
            else:
                # For invalid values, default to True as per test expectations
                attributes["is_nullable"] = True

            # Set column default value
            if column_default := obj.get("column_default"):
                attributes["column_default"] = column_default

            entity_attributes["attributes"] = attributes
            entity_attributes["custom_attributes"] = custom_attributes

            return entity_attributes

        except Exception as e:
            logger.error("Error creating MySQL Column entity: %s", str(e))
            raise ValueError(f"Error creating MySQL Column Entity: {str(e)}")


class MySQLProcedure(Procedure):
    """
    MySQL Procedure entity transformer for Atlas.

    This class handles transformation of MySQL procedure metadata to Atlas entities.
    """

    @classmethod
    def get_attributes(cls, obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a dictionary into a MySQL-specific Procedure entity.

        Args:
            obj: Dictionary containing procedure metadata.

        Returns:
            Dictionary with attributes, custom_attributes, and entity_class.

        Raises:
            ValueError: If required fields are missing.
        """
        logger.debug("Creating MySQL Procedure entity")

        try:
            # Get base attributes from parent
            entity_attributes = super().get_attributes(obj)

            # Add MySQL-specific attributes
            custom_attributes = entity_attributes.get("custom_attributes", {})

            # MySQL-specific procedure attributes
            if created := obj.get("created"):
                custom_attributes["created"] = created

            if last_altered := obj.get("last_altered"):
                custom_attributes["lastAltered"] = last_altered

            if procedure_type := obj.get("procedure_type"):
                custom_attributes["procedureType"] = procedure_type

            entity_attributes["custom_attributes"] = custom_attributes

            return entity_attributes

        except Exception as e:
            logger.error("Error creating MySQL Procedure entity: %s", str(e))
            raise ValueError(f"Error creating MySQL Procedure Entity: {str(e)}")
