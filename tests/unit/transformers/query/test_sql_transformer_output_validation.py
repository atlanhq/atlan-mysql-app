import glob
import json
import os
from typing import Any, Dict, List

import daft
import pytest
from application_sdk.observability.logger_adaptor import get_logger
from application_sdk.transformers.query import QueryBasedTransformer

logger = get_logger(__name__)

LAST_SYNC_WORKFLOW_NAME = "79a40801-07c2-4852-86c4-9703bda3a840"
LAST_SYNC_RUN = "019667f9-31e9-77b0-b7c0-b901bd30d140"
CONNECTOR_NAME = "mysql"
TENANT_ID = "default"
CONNECTION_QUALIFIED_NAME = "default/mysql/1745501106"
CONNECTION_NAME = "dev"


@pytest.fixture
def sql_transformer():
    return QueryBasedTransformer(connector_name=CONNECTOR_NAME, tenant_id=TENANT_ID)


def get_raw_json_files():
    """
    Get all JSON files from the resources/raw directory using glob
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    resources_dir = os.path.join(current_dir, "resources/raw")
    return glob.glob(os.path.join(resources_dir, "*.json"))


def remove_run_time_sensitive_fields(row: Dict[str, Any]):
    """
    Remove run time sensitive fields from a row
    E.g time sensitive fields: lastSyncRunAt, createdAt, updatedAt which can change on each run
    """
    if row["attributes"].get("lastSyncRunAt"):
        row["attributes"].pop("lastSyncRunAt")
    if row["attributes"].get("sourceCreatedAt"):
        row["attributes"].pop("sourceCreatedAt")


def test_transform_metadata_output_validation(
    sql_transformer: QueryBasedTransformer,
):
    """
    Test the complete transformation flow for all JSON files in resources:
    1. Read raw JSON from resources using daft.read_json
    2. Transform using SQL transformer
    3. Validate output
    """
    test_files = get_raw_json_files()
    assert len(test_files) > 0, "No test files found in resources directory"
    logger.info(f"Found {len(test_files)} test files to process")

    for json_file in test_files:
        file_name = os.path.basename(json_file).removesuffix(".json").upper()
        logger.info(f"Testing for Asset: {file_name}")

        # Read the json file into a Daft DataFrame
        input_df = daft.read_json(json_file)

        # Transform using SQL transformer
        result = sql_transformer.transform_metadata(
            file_name,
            input_df,
            LAST_SYNC_WORKFLOW_NAME,
            LAST_SYNC_RUN,
            connection_qualified_name=CONNECTION_QUALIFIED_NAME,
            connection_name=CONNECTION_NAME,
        )

        # Assert that the result is not None and has rows
        assert result is not None
        assert result.count_rows() > 0

        # convert the transformed Daft DataFrame to a list of records
        transformed_result_ouput = result.to_pylist()

        # read the expected transformed json file
        expected_transformed_path = json_file.replace("/raw", "/transformed")
        if not os.path.exists(expected_transformed_path):
            logger.warning(
                f"Expected transformed file not found: {expected_transformed_path}, skipping."
            )
            continue  # Skip this test if expected file is missing
        expected_transformed_output: List[Dict[str, Any]] = []
        with open(expected_transformed_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    expected_transformed_output.append(json.loads(line))

        # assert that the number of records in the transformed output is the same as the expected output
        assert len(transformed_result_ouput) == len(expected_transformed_output)
        logger.info(
            f"Validating {len(transformed_result_ouput)} records for {file_name}"
        )

        # validate each record in the transformed output with the expected output
        for idx, (expected, actual) in enumerate(
            zip(expected_transformed_output, transformed_result_ouput)
        ):
            logger.info(f"Validating record {idx + 1} of {file_name}")
            remove_run_time_sensitive_fields(expected)
            remove_run_time_sensitive_fields(actual)
            assert expected == actual
            logger.info(f"Record {idx + 1} validation successful")

        logger.info(f"All records validated successfully for {file_name}")
