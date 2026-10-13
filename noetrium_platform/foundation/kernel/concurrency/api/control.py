from __future__ import annotations

from threading import Event
from typing import Callable

from .contracts import Deadline


class UnboundedExecutionControl:
    """Canonical runtime control for work with no enclosing deadline."""

    __slots__ = ()
    _never = Event()

    @property
    def cancelled(self) -> bool:
        return False

    @property
    def reason(self) -> str | None:
        return None

    @property
    def deadline(self) -> Deadline | None:
        return None

    @property
    def remaining_seconds(self) -> float | None:
        return None

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("execution control wait timeout cannot be negative")
        return self._never.wait(timeout)

    def checkpoint(self) -> None:
        return None

    def subscribe_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        # This authority can never cancel. A valid subscription is inert and
        # does not create a polling thread or timer.
        if not callable(callback):
            raise TypeError("cancellation listener must be callable")
        return lambda: None


UNBOUNDED_EXECUTION_CONTROL = UnboundedExecutionControl()


__all__ = [
    "UNBOUNDED_EXECUTION_CONTROL",
    "UnboundedExecutionControl",
]
