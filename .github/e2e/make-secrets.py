"""Write the SDR test secrets bundle for the MySQL connector.

Reads E2E_MYSQL_USERNAME / E2E_MYSQL_PASSWORD from env (defaulting to the
``.github/e2e/seed.sql`` credentials so the self-contained sibling-MySQL
stack works with no extra secrets) and writes them under the secret-store
key ``mysql-credentials`` (referenced as ``secret-path`` in agent_json) to
``.github/e2e/secrets/credentials.json`` — the canonical SDR test secrets
path the SDK secretstore component reads.

The bundle is JSON-encoded as a string because the Dapr local.file secret
store with ``nestedSeparator=":"`` expects nested-bundle-as-string on
lookup.
"""

from __future__ import annotations

import json
import os

bundle = {
    "username": os.environ.get("E2E_MYSQL_USERNAME", "e2e_user"),
    "password": os.environ.get("E2E_MYSQL_PASSWORD", "e2e_pass"),
}
out = {"mysql-credentials": json.dumps(bundle)}

os.makedirs(".github/e2e/secrets", exist_ok=True)
with open(".github/e2e/secrets/credentials.json", "w") as f:
    json.dump(out, f)
print("Wrote .github/e2e/secrets/credentials.json")
