from __future__ import annotations

import pytest

from tests._concurrency_support import drain_test_concurrency_runtimes


@pytest.fixture(autouse=True)
def _close_test_concurrency_runtimes():
    """Make the pytest test boundary the explicit owner of helper runtimes."""

    yield
    drain_test_concurrency_runtimes()
