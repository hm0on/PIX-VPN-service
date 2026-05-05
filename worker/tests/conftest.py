"""Shared pytest fixtures for the worker test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app.*` importable when tests are run from the worker root.
_WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKER_ROOT))
