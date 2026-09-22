"""Root test conftest.

The only thing this file does is pin the observability identity **before any
test module imports application_sdk**.

``application_sdk.constants`` snapshots ``ATLAN_APPLICATION_NAME`` and
``ATLAN_DEPLOYMENT_NAME`` at import time, and the SDK's integration fixtures
refuse to run when the live environment disagrees with that snapshot
(``IntegrationEnvOrderingError``). ``tests/integration/conftest.py`` used to be
the only place that set them, which works when the integration suite is run on
its own — but pytest collects ``tests/e2e`` first, and that module imports
application_sdk with the variables still unset, so the snapshot is ``default``
and the integration conftest's later ``setdefault`` contradicts it. Any run
that collects the whole ``tests/`` tree then dies during collection.

The conformance preflight runner (F016) always points pytest at the whole
tree, so this is not merely tidiness: without it, no behavioural preflight
scenario can execute. Setting the pair here, at the root conftest, is the
SDK's own prescribed fix applied at the level that covers every suite.
"""

from __future__ import annotations

import os

os.environ.setdefault("ATLAN_APPLICATION_NAME", "mysql")
os.environ.setdefault("ATLAN_DEPLOYMENT_NAME", "ci")
