from __future__ import annotations

from contextlib import contextmanager
from threading import Condition
from typing import Callable, Iterator

from .ports import CancellationTokenPort


@contextmanager
def wake_on_cancellation(
    cancellation: CancellationTokenPort | None,
    condition: Condition,
    *,
    notify_waiters: Callable[[], None],
) -> Iterator[None]:
    """Wake a condition on the actual cancellation transition, without polling.

    Subscription precedes acquisition of the condition lock. A cancellation
    that races with registration is detected by the caller's next checkpoint;
    subsequent transitions notify without inventing a timer or capacity.
    """
    if cancellation is None:
        yield
        return

    def wake() -> None:
        with condition:
            notify_waiters()

    unsubscribe = cancellation.subscribe_cancel(wake)
    try:
        yield
    finally:
        unsubscribe()


__all__ = ["wake_on_cancellation"]
