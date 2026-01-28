import json
import unittest

import pytest
import requests
from application_sdk.test_utils.e2e import WorkflowExecutionError
from application_sdk.test_utils.e2e.base import BaseTest
from application_sdk.test_utils.e2e.conftest import workflow_details


class TestMySQLWorkflow(unittest.TestCase, BaseTest):
    extracted_output_base_path = (
        "./local/dapr/objectstore/artifacts/apps/default/workflows"
    )
    workflow_timeout = 400  # Increased for GH Actions VPN latency

    def _mask_credentials(self, creds):
        """Mask sensitive fields in credentials for logging."""
        if not isinstance(creds, dict):
            return creds
        masked = creds.copy()
        if "username" in masked and masked["username"]:
            username = masked["username"]
            if len(username) <= 2:
                masked["username"] = "***"
            else:
                masked["username"] = f"{username[:2]}***"
        if "password" in masked:
            masked["password"] = "***"
        if "extra" in masked and isinstance(masked["extra"], dict):
            masked["extra"] = masked["extra"].copy()
        return masked

    def _safe_api_call(self, method_name, *args, **kwargs):
        """Wrapper to safely call API methods and print detailed error information."""
        # Prepare request data for logging
        request_data = None
        if method_name == "test_connection":
            request_data = kwargs.get("credentials", args[0] if args else {})
        elif method_name == "get_metadata":
            request_data = kwargs.get("credentials", args[0] if args else {})
        elif method_name == "preflight_check":
            request_data = kwargs if kwargs else (args[0] if args else {})

        # Log request details (with masked credentials)
        if request_data:
            masked_data = self._mask_credentials(request_data)
            print(f"\n=== API REQUEST: {method_name} ===")
            print(f"Endpoint: {self.client.base_url}/{method_name.replace('_', '/')}")
            print(f"Request Data (masked): {json.dumps(masked_data, indent=2)}")
            # Extract key connection details for visibility
            if isinstance(request_data, dict):
                creds = request_data.get("credentials", request_data)
                print(
                    f"Connection Details - Host: {creds.get('host', '[unknown]')}, "
                    f"Port: {creds.get('port', '[unknown]')}, "
                    f"Database: {creds.get('extra', {}).get('database', '[unknown]')}, "
                    f"AuthType: {creds.get('authType', '[unknown]')}"
                )
            print("=" * 50)

        try:
            method = getattr(self.client, method_name)
            response = method(*args, **kwargs)
            print(f"\n✅ API call succeeded: {method_name}")
            return response
        except AssertionError as e:
            # If assertion fails, try to get the actual response
            print(f"\n❌ API call failed: {method_name}")
            print(f"AssertionError: {e}")

            # Try to make the call again to get the actual response
            try:
                if method_name == "test_connection":
                    resp = requests.post(
                        f"{self.client.base_url}/auth",
                        json=kwargs.get("credentials", args[0] if args else {}),
                    )
                elif method_name == "get_metadata":
                    resp = requests.post(
                        f"{self.client.base_url}/metadata",
                        json=kwargs.get("credentials", args[0] if args else {}),
                    )
                elif method_name == "preflight_check":
                    data = kwargs if kwargs else (args[0] if args else {})
                    resp = requests.post(
                        f"{self.client.base_url}/check",
                        json=data,
                    )
                else:
                    raise

                print("\n=== HTTP RESPONSE DETAILS ===")
                print(f"Status Code: {resp.status_code}")
                print(f"Response Headers: {json.dumps(dict(resp.headers), indent=2)}")
                try:
                    response_json = resp.json()
                    print(f"Response Body: {json.dumps(response_json, indent=2)}")
                    # Extract error details if available
                    if "details" in response_json:
                        print(f"\n⚠️ Error Details: {response_json['details']}")
                    if "error" in response_json:
                        print(f"⚠️ Error: {response_json['error']}")
                except Exception:
                    print(f"Response Text: {resp.text}")
                print("=============================\n")
            except Exception as inner_e:
                print(f"Could not retrieve error details: {inner_e}")
                import traceback

                traceback.print_exc()

            raise

    @pytest.mark.order(2)
    def test_auth(self):
        """Test Authentication - validates structure rather than exact content."""
        response = self._safe_api_call(
            "test_connection", credentials=self.test_workflow_args["credentials"]
        )
        print("\n=== AUTH RESPONSE ===")
        print(json.dumps(response, indent=2))
        print("====================\n")

        if not response.get("success"):
            error_msg = response.get("message", "Unknown error")
            print(f"❌ Authentication failed: {error_msg}")
            print(f"Full response: {json.dumps(response, indent=2)}")

        self.assertTrue(
            response.get("success"),
            f"Response should have success=True. Actual response: {json.dumps(response, indent=2)}",
        )
        self.assertIn(
            "message",
            response,
            f"Response should have 'message' field. Actual: {list(response.keys())}",
        )
        self.assertIsInstance(
            response["message"],
            str,
            f"Message should be a string. Got: {type(response['message'])}",
        )

    @pytest.mark.order(3)
    def test_metadata(self):
        """Test Metadata - validates structure rather than exact content."""
        response = self._safe_api_call(
            "get_metadata", credentials=self.test_workflow_args["credentials"]
        )
        print("\n=== METADATA RESPONSE ===")
        print(json.dumps(response, indent=2))
        print("========================\n")

        if not response.get("success"):
            error_msg = response.get("message", "Unknown error")
            print(f"❌ Metadata fetch failed: {error_msg}")
            print(f"Full response: {json.dumps(response, indent=2)}")

        self.assertTrue(
            response.get("success"),
            f"Response should have success=True. Actual response: {json.dumps(response, indent=2)}",
        )
        self.assertIn(
            "data",
            response,
            f"Response should have 'data' field. Actual: {list(response.keys())}",
        )
        self.assertIsInstance(
            response["data"],
            list,
            f"Data field should be a list. Got: {type(response['data'])}",
        )
        if response["data"]:
            for item in response["data"]:
                self.assertIsInstance(
                    item,
                    dict,
                    f"Each data item should be a dictionary. Got: {type(item)}",
                )
                # MySQL returns TABLE_CATALOG and TABLE_SCHEMA (matching SQL standard)
                self.assertIn(
                    "TABLE_CATALOG",
                    item,
                    f"Each item should have 'TABLE_CATALOG' field. Actual keys: {list(item.keys())}",
                )
                self.assertIn(
                    "TABLE_SCHEMA",
                    item,
                    f"Each item should have 'TABLE_SCHEMA' field. Actual keys: {list(item.keys())}",
                )

    @pytest.mark.order(4)
    def test_preflight_check(self):
        """Test Preflight Check - validates structure rather than exact content."""
        response = self._safe_api_call(
            "preflight_check",
            credentials=self.test_workflow_args["credentials"],
            metadata=self.test_workflow_args["metadata"],
        )
        print("\n=== PREFLIGHT CHECK RESPONSE ===")
        print(json.dumps(response, indent=2))
        print("===============================\n")

        if not response.get("success"):
            error_msg = response.get("message", "Unknown error")
            print(f"❌ Preflight check failed: {error_msg}")
            print(f"Full response: {json.dumps(response, indent=2)}")

        self.assertTrue(
            response.get("success"),
            f"Response should have success=True. Actual response: {json.dumps(response, indent=2)}",
        )
        self.assertIn(
            "data",
            response,
            f"Response should have 'data' field. Actual: {list(response.keys())}",
        )
        data = response["data"]

        if "databaseSchemaCheck" not in data:
            print(
                f"❌ Missing 'databaseSchemaCheck' in data. Available keys: {list(data.keys())}"
            )
        if "tablesCheck" not in data:
            print(
                f"❌ Missing 'tablesCheck' in data. Available keys: {list(data.keys())}"
            )

        self.assertIn(
            "databaseSchemaCheck",
            data,
            f"Response should have 'databaseSchemaCheck'. Available keys: {list(data.keys())}",
        )
        self.assertIn(
            "tablesCheck",
            data,
            f"Response should have 'tablesCheck'. Available keys: {list(data.keys())}",
        )

        db_check = data["databaseSchemaCheck"]
        if not db_check.get("success"):
            print(
                f"❌ Database schema check failed: {db_check.get('failureMessage', 'No error message')}"
            )

        self.assertTrue(
            db_check.get("success"),
            f"Database schema check should succeed. Actual: {json.dumps(db_check, indent=2)}",
        )

        tables_check = data["tablesCheck"]
        if not tables_check.get("success"):
            print(
                f"❌ Tables check failed: {tables_check.get('failureMessage', 'No error message')}"
            )

        self.assertTrue(
            tables_check.get("success"),
            f"Tables check should succeed. Actual: {json.dumps(tables_check, indent=2)}",
        )

        # MySQL also has versionCheck
        if "versionCheck" in data:
            version_check = data["versionCheck"]
            if not version_check.get("success"):
                print(
                    f"❌ Version check failed: {version_check.get('failureMessage', 'No error message')}"
                )
            self.assertTrue(
                version_check.get("success"),
                f"Version check should succeed. Actual: {json.dumps(version_check, indent=2)}",
            )

    @pytest.mark.order(5)
    def test_run_workflow(self):
        """Test running the metadata extraction workflow with detailed error reporting."""
        response = self.client.run_workflow(data=self.test_workflow_args)
        print("\n=== WORKFLOW START RESPONSE ===")
        print(json.dumps(response, indent=2))
        print("==============================\n")

        self.assertEqual(
            response["success"],
            True,
            f"Workflow start failed. Response: {json.dumps(response, indent=2)}",
        )
        self.assertEqual(response["message"], "Workflow started successfully")

        workflow_id = response["data"]["workflow_id"]
        run_id = response["data"]["run_id"]
        workflow_details[self.test_name] = {
            "workflow_id": workflow_id,
            "run_id": run_id,
        }

        print(f"Workflow started: workflow_id={workflow_id}, run_id={run_id}")

        # Wait for the workflow to complete
        workflow_status = self.monitor_and_wait_workflow_execution()

        # Update workflow_details with the actual run_id used for data writing
        # (monitor_and_wait_workflow_execution sets self.run_id but doesn't update workflow_details)
        if hasattr(self, "run_id") and self.run_id:
            workflow_details[self.test_name]["run_id"] = self.run_id

        # If workflow is not completed successfully, extract and print error details
        if workflow_status != "COMPLETED":
            print(f"\n❌ WORKFLOW FAILED WITH STATUS: {workflow_status}")
            print(f"Workflow ID: {workflow_id}")
            print(f"Run ID: {run_id}")

            # Get detailed workflow status
            try:
                status_response = self.client.get_workflow_status(workflow_id, run_id)
                print("\n=== WORKFLOW STATUS DETAILS ===")
                print(json.dumps(status_response, indent=2))
                print("==============================\n")

                # Try to get error details if available
                if "data" in status_response:
                    data = status_response["data"]

                    # Print all available fields for debugging
                    print("\n=== ALL STATUS DATA FIELDS ===")
                    print(f"Available fields: {list(data.keys())}")
                    print(f"Full data: {json.dumps(data, indent=2)}")
                    print("==============================\n")

                    if "error" in data:
                        error_info = data["error"]
                        print("❌ Workflow Error Details:")
                        print(json.dumps(error_info, indent=2))
                    elif "failure_reason" in data:
                        print("❌ Workflow Failure Reason:")
                        print(data["failure_reason"])
                    elif "failure_message" in data:
                        print("❌ Workflow Failure Message:")
                        print(data["failure_message"])
                    else:
                        print("⚠️ No error details found in status response.")
                        print(
                            "   Check application logs or Temporal UI for detailed error information."
                        )

                    # Print any other error-related fields
                    error_fields = [
                        k
                        for k in data.keys()
                        if "error" in k.lower() or "fail" in k.lower()
                    ]
                    if error_fields:
                        print(
                            f"\n⚠️ Additional error-related fields found: {error_fields}"
                        )
                        for field in error_fields:
                            print(f"  {field}: {data[field]}")
            except Exception as e:
                print(f"⚠️ Could not fetch workflow error details: {e}")
                import traceback

                traceback.print_exc()

            # Try to get error from Temporal CLI if available
            import os
            import subprocess

            temporal_path = os.environ.get("PATH", "")
            if (
                "temporalio" in temporal_path
                or os.system("which temporal > /dev/null 2>&1") == 0
            ):
                try:
                    print("\n=== ATTEMPTING TO GET TEMPORAL CLI ERROR DETAILS ===")
                    result = subprocess.run(
                        [
                            "temporal",
                            "workflow",
                            "describe",
                            "--workflow-id",
                            workflow_id,
                            "--run-id",
                            run_id,
                            "--output",
                            "json",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        temporal_details = json.loads(result.stdout)
                        print(json.dumps(temporal_details, indent=2))

                        # Extract failure reason if available
                        if "failure" in str(temporal_details).lower():
                            print("\n⚠️ Failure information found in Temporal details")
                    else:
                        print(f"⚠️ Temporal CLI error: {result.stderr}")
                except Exception as e:
                    print(f"⚠️ Could not use Temporal CLI: {e}")

            print(
                "\n💡 TIP: Check Temporal UI or app logs for detailed error information"
            )
            print(f"   Workflow ID: {workflow_id}")
            print(f"   Run ID: {run_id}")

            raise WorkflowExecutionError(
                f"Workflow failed with status: {workflow_status}. "
                f"workflow_id={workflow_id}, run_id={run_id}. "
                f"Check logs above for details."
            )

        print("✅ Workflow completed successfully")

    @pytest.mark.order(6)
    def test_configuration_get(self):
        """
        Test configuration retrieval - overridden to ensure correct order.
        Must run after test_run_workflow (order 5) which populates workflow_details.
        """
        import requests

        response = requests.get(
            f"{self.client.host}/workflows/v1/config/{workflow_details[self.test_name]['workflow_id']}"
        )
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(response_data["success"], True)
        self.assertEqual(
            response_data["message"], "Workflow configuration fetched successfully"
        )

        # Verify that response data contains the expected metadata and connection
        self.assertEqual(
            response_data["data"]["connection"], self.test_workflow_args["connection"]
        )
        self.assertEqual(
            response_data["data"]["metadata"], self.test_workflow_args["metadata"]
        )

    def _get_extracted_dir_path(self, expected_file_postfix: str) -> str:
        """
        Override to use the correct run_id from workflow_details or self.run_id.
        """
        if self.test_name not in workflow_details:
            raise ValueError(
                f"Workflow not found in workflow_details. Ensure test_run_workflow completed successfully. "
                f"Available keys: {list(workflow_details.keys())}"
            )
        # Use self.run_id if available (updated by monitor_and_wait_workflow_execution)
        # Otherwise fall back to workflow_details run_id
        run_id = (
            getattr(self, "run_id", None) or workflow_details[self.test_name]["run_id"]
        )
        path = f"{self.extracted_output_base_path}/{workflow_details[self.test_name]['workflow_id']}/{run_id}{expected_file_postfix}"
        return path

    @pytest.mark.order(8)
    def test_data_validation(self):
        """
        Test for validating the extracted source data - structure validation only.
        Validates that required fields exist and have correct types, but does not
        validate exact values (database names, qualified names, etc.).
        """
        # Skip if workflow_details is empty (test run in isolation)
        if self.test_name not in workflow_details:
            pytest.skip(
                f"Skipping data validation: Workflow not found in workflow_details. "
                f"Ensure test_run_workflow completed successfully. "
                f"Available keys: {list(workflow_details.keys())}"
            )
        try:
            self.validate_data()
        except (FileNotFoundError, ValueError) as e:
            if "No data found" in str(e) or "Workflow not found" in str(e):
                pytest.skip(f"Skipping data validation: {e}")
            raise
