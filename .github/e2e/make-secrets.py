"""Write the SDR test secrets bundle for the MySQL connector.

Writes the seed-DB credentials (constants matching docker-compose.ci.yml)
under the secret-store key ``mysql-credentials`` (referenced as
``secret-path`` in agent_json) to ``.github/e2e/secrets/credentials.json``
— the canonical SDR test secrets path the SDK secretstore component reads.

These are CI-only constants for the throwaway mysql:8.0 container, not
real secrets. Keeping them out of repo-level GitHub Actions secrets makes
the SDR suite self-contained: anyone can run it locally with
``docker compose -f ... up``, no secrets fetch required.

The bundle is JSON-encoded as a string because the Dapr local.file secret
store with ``nestedSeparator=":"`` expects nested-bundle-as-string on
lookup.
"""

from __future__ import annotations

import json
import os

# Must match docker-compose.ci.yml's mysql service env vars.
bundle = {
    "username": "e2e_user",
    "password": "e2e_pass",
}

out = {"mysql-credentials": json.dumps(bundle)}

os.makedirs(".github/e2e/secrets", exist_ok=True)
with open(".github/e2e/secrets/credentials.json", "w") as f:
    json.dump(out, f)
print("Wrote .github/e2e/secrets/credentials.json")
