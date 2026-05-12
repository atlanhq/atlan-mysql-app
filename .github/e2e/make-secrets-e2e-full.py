"""e2e-full test secrets bundle for the MySQL connector.

Same shape as `make-secrets.py` (the per-PR SDR integration suite),
re-keyed for the e2e-full AGENT flow. The SDK's :func:`application_sdk
.testing.full_dag.payload.build_ae_payload` emits
``agent-json.basic.username = "SDR_MYSQL_USERNAME"`` and
``agent-json.basic.password = "SDR_MYSQL_PASSWORD"`` (matching the
existing devex SDR convention). The CI worker resolves those keys
against the local.file Dapr secret store, which reads this JSON.

CI-only constants for the throwaway mysql:8.0 sibling — same creds
the e2e-full docker-compose overlay sets on the mysql container.
"""

from __future__ import annotations

import json
import os

# Must match the MYSQL_USER/MYSQL_PASSWORD in
# e2e-full-docker-compose.yaml (and seed.sql's GRANT statements).
#
# e2e-full uses agent `key-type: single-key`, which makes the SDK
# fetch each ref-key as a separate top-level entry from the Dapr
# secret store (see application_sdk.credentials.agent._fetch_per_
# key_bundle). So the bundle file is FLAT — not nested under
# `mysql-credentials` like the per-PR integration suite (which uses
# `secret-path` / multi-key bundle mode).
out = {
    "SDR_MYSQL_USERNAME": "e2e_user",
    "SDR_MYSQL_PASSWORD": "e2e_pass",
}

os.makedirs(".github/e2e/secrets", exist_ok=True)
with open(".github/e2e/secrets/credentials.json", "w") as f:
    json.dump(out, f)
print("Wrote .github/e2e/secrets/credentials.json (e2e-full bundle)")
