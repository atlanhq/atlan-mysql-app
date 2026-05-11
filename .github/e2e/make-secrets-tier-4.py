"""Tier-4 SDR test secrets bundle for the MySQL connector.

Same shape as `make-secrets.py` (tier 3) but keyed for the tier-4
agent flow. The SDK's :func:`application_sdk.testing.full_dag.payload.build_ae_payload`
emits ``agent-json.basic.username = "SDR_MYSQL_USERNAME"`` and
``agent-json.basic.password = "SDR_MYSQL_PASSWORD"`` (matching the
existing dev-tenant SDR convention). The CI worker resolves those keys
against the local.file Dapr secret store, which reads this JSON.

CI-only constants for the throwaway mysql:8.0 sibling — same creds
the tier-4 docker-compose overlay sets on the mysql container.
"""

from __future__ import annotations

import json
import os

# Must match the MYSQL_USER/MYSQL_PASSWORD in tier-4-docker-compose.yaml
# (and seed.sql's GRANT statements).
#
# Tier-4 uses agent `key-type: single-key`, which makes the SDK fetch
# each ref-key as a separate top-level entry from the Dapr secret store
# (see application_sdk.credentials.agent._fetch_per_key_bundle).
# So the bundle file is FLAT — not nested under `mysql-credentials`
# like tier-3 (which uses `secret-path` / multi-key bundle mode).
out = {
    "SDR_MYSQL_USERNAME": "e2e_user",
    "SDR_MYSQL_PASSWORD": "e2e_pass",
}

os.makedirs(".github/e2e/secrets", exist_ok=True)
with open(".github/e2e/secrets/credentials.json", "w") as f:
    json.dump(out, f)
print("Wrote .github/e2e/secrets/credentials.json (tier-4 bundle)")
