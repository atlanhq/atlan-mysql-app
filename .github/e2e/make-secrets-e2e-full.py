"""e2e-full test secrets bundle for the MySQL connector.

The SDK's :func:`application_sdk.testing.e2e.payload.build_ae_payload`
emits ``agent-json.basic.username = "SDR_MYSQL_USERNAME"`` and
``agent-json.basic.password = "SDR_MYSQL_PASSWORD"``. The CI worker resolves
those keys against the local.file Dapr secret store, which reads this JSON.

CI-only constants for the throwaway mysql:8.0 sibling — same creds the
e2e-full docker-compose overlay sets on the mysql container.
"""

from __future__ import annotations

import json
import os

# Must match MYSQL_USER/MYSQL_PASSWORD in e2e-full-docker-compose.yaml
# and seed.sql's GRANT statements.
# Flat (single-key) format: the SDK fetches each key as a top-level
# entry from the Dapr secret store (key-type: single-key).
out = {
    "SDR_MYSQL_USERNAME": "e2e_user",
    "SDR_MYSQL_PASSWORD": "e2e_pass",
}

os.makedirs(".github/e2e/secrets", exist_ok=True)
with open(".github/e2e/secrets/credentials.json", "w") as f:
    json.dump(out, f)
print("Wrote .github/e2e/secrets/credentials.json (e2e-full bundle)")
