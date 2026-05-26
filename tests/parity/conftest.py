"""Parity test conftest — loads credentials from tests/.env."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Add parity dir to path so test files can import api_recorder
_PARITY_DIR = Path(__file__).resolve().parent
if str(_PARITY_DIR) not in sys.path:
    sys.path.insert(0, str(_PARITY_DIR))

_ENV_FILE = _PARITY_DIR.parent / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)
