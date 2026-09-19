from __future__ import annotations

from collections.abc import Callable
from time import monotonic, sleep
from typing import TypeVar


T = TypeVar("T")


def retry_until_deadline(
    operation: Callable[[], T],
    *,
    should_retry: Callable[[Exception], bool],
    timeout_seconds: float,
    interval_seconds: float = 0.01,
) -> T:
    """Retry one synchronous operation until success or its absolute deadline.

    The primitive owns retry scheduling only. Callers retain authority over the
    operation and the exact exception classification that is transient.
    """

    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be >= 0")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            return operation()
        except Exception as exc:
            remaining = deadline - monotonic()
            if not should_retry(exc) or remaining <= 0:
                raise
            sleep(min(interval_seconds, remaining))


__all__ = ["retry_until_deadline"]
