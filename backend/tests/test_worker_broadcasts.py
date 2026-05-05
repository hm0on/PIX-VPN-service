"""Placeholder forwarder — the actual worker broadcast tests live in
``worker/tests/test_broadcasts.py`` because they import from the worker
package and run inside the worker test environment. We keep this file so
contributors can find the tests by name from the backend tree.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Worker broadcast tests live under worker/tests/test_broadcasts.py. "
    "Run `pytest worker/tests` to exercise them.",
    allow_module_level=True,
)
