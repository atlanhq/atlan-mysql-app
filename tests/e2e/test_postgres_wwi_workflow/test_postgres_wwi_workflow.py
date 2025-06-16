import unittest

import pytest
from application_sdk.observability.logger_adaptor import get_logger
from application_sdk.test_utils.e2e.base import BaseTest

logger = get_logger(__name__)


class TestPostgresWWIWorkflow(unittest.TestCase, BaseTest):
    @pytest.mark.order(1)
    def test_health_check(self):
        pass

    @pytest.mark.order(2)
    def test_auth(self):
        pass

    @pytest.mark.order(3)
    def test_metadata(self):
        pass

    @pytest.mark.order(4)
    def test_preflight_check(self):
        pass

    @pytest.mark.order(6)
    def test_data_validation(self):
        """
        Test for validating the extracted source data
        """
        self.validate_data()
