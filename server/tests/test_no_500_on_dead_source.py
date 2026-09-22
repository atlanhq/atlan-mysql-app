"""No serving route may answer a dead source with a 500.

The SDK's generic fetch_metadata states the contract outright — "boundary:
empty list to the UI, never 500". Overriding the method does not exempt us: a
raised error renders as "Internal server error" in the connector form's schema
picker, which tells the customer nothing and looks like our fault even when the
source is simply unreachable.

This is not hypothetical. Both of this connector's overridden fetch_metadata
implementations leaked a 500 against an unreachable host until this test existed.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from mysql_server import get_asgi_app

_DEAD = [
    {"key": "host", "value": "unreachable.invalid"},
    {"key": "port", "value": "3306"},
    {"key": "username", "value": "u"},
    {"key": "password", "value": "p"},
    {"key": "database", "value": "d"},
    {"key": "extra.database", "value": "d"},
    {"key": "account", "value": "unreachable.invalid"},
    {"key": "authType", "value": "basic"},
]


async def _post(app, path: str, payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [(b"host", b"x.local"), (b"content-type", b"application/json")],
        "client": ("1.2.3.4", 1),
        "server": ("h", 80),
    }
    status, out, sent = [None], [b""], [False]

    async def receive():
        if sent[0]:
            return {"type": "http.disconnect"}
        sent[0] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status[0] = message["status"]
        elif message["type"] == "http.response.body":
            out[0] += message.get("body", b"")

    await app(scope, receive, send)
    return status[0], out[0]


class TestNoFiveHundredOnADeadSource(unittest.TestCase):
    def test_every_post_route_returns_a_verdict_not_a_500(self):
        app = get_asgi_app()
        payload = {"credentials": _DEAD, "metadata": {}}

        async def drive():
            results = {}
            for path in (
                "/workflows/v1/auth",
                "/workflows/v1/check",
                "/workflows/v1/metadata",
            ):
                results[path] = (
                    await asyncio.wait_for(_post(app, path, payload), timeout=90)
                )[0]
            return results

        statuses = asyncio.run(drive())
        leaked = {p: s for p, s in statuses.items() if s == 500}
        self.assertEqual(
            leaked,
            {},
            "a dead source must produce a typed verdict, not an Internal Server "
            f"Error: {leaked}",
        )

    def test_metadata_returns_an_empty_list_rather_than_failing(self):
        """The schema picker shows nothing, which is honest; a 500 is not."""
        app = get_asgi_app()
        payload = {"credentials": _DEAD, "metadata": {}}
        status, body = asyncio.run(
            asyncio.wait_for(_post(app, "/workflows/v1/metadata", payload), timeout=90)
        )
        self.assertEqual(status, 200)
        parsed = json.loads(body)
        self.assertEqual(parsed.get("data"), [])


if __name__ == "__main__":
    unittest.main()
