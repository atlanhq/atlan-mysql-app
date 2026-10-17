"""The serving path must never mutate process-global state.

The consolidated host runs several apps in ONE process with ONE environment.
The worker generates an RDS IAM token by writing AWS_ACCESS_KEY_ID and
AWS_SECRET_ACCESS_KEY into os.environ so boto3's default chain picks them up,
then restoring them in a finally. Carried into the host that is a live fault,
not untidiness:

* another app reading AWS credentials inside that window gets this tenant's
  customer keys;
* two overlapping requests interleave and the second restore clobbers the
  first;
* boto3 prefers env credentials over the pod's IRSA identity, so the host can
  try to reach its own bucket as the customer.

test_auth and preflight_check both reach that path, so an IAM-role connection
triggers it on every call. These tests are what stop it coming back.
"""

from __future__ import annotations

import ast
import os
import pathlib
import unittest
from unittest import mock

from mysql_server.client import MySQLServerClient

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "mysql_server"

_AWS_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


class TestNoEnvironmentWrites(unittest.TestCase):
    def test_no_module_assigns_into_os_environ(self):
        """Static sweep: nothing in the package may write to os.environ.

        Static because the write is inside a network call path that a unit test
        cannot reach without AWS — and a rule this cheap to state should not
        depend on reaching it.
        """
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "environ"
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")
                # os.environ.setdefault / update / pop are writes too
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    value = node.func.value
                    if (
                        isinstance(value, ast.Attribute)
                        and value.attr == "environ"
                        and node.func.attr in ("setdefault", "update", "pop", "clear")
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno} ({node.func.attr})"
                        )
        self.assertEqual(
            offenders,
            [],
            "the serving path shares one process with every other hosted app, "
            "so a process-global write is a cross-app fault: " + ", ".join(offenders),
        )

    def test_building_an_iam_url_leaves_aws_credentials_alone(self):
        """Driven, not just static: exercise the IAM path and watch the env.

        The AWS calls are stubbed — what is under test is this package's
        handling of credentials, not boto3.
        """
        before = {key: os.environ.get(key) for key in _AWS_KEYS}
        creds = {
            "host": "db-1.eu-west-1.rds.amazonaws.com",
            "port": "3306",
            "username": "AKIAEXAMPLE",
            "password": "secret-key",
            "extra": {"username": "app_user"},
        }
        fake_rds = mock.Mock()
        fake_rds.generate_db_auth_token.return_value = "a-token"
        with mock.patch("mysql_server.client.create_aws_session") as session:
            with mock.patch(
                "mysql_server.client.create_aws_client", return_value=fake_rds
            ):
                url = MySQLServerClient()._iam_user_url(creds)

        self.assertIn("app_user", url)
        session.assert_called_once()
        # The session is built FROM the credentials, which is the whole point.
        self.assertIs(session.call_args[0][0], creds)
        after = {key: os.environ.get(key) for key in _AWS_KEYS}
        self.assertEqual(before, after, "IAM token generation mutated the environment")


if __name__ == "__main__":
    unittest.main()
