from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock
import time
from typing import Callable

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionLaneKind, TaskCancelled, TaskDeadlineExceeded
from noetrium_platform.foundation.kernel.concurrency.api.ports import CancellationTokenPort, TaskContextPort

class _DeadlineOwner(Enum):
    NONE = "none"
    GROUP = "group"
    TASK = "task"



class _CancellationState(CancellationTokenPort):
    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason: str | None = None
        self._cancelled_monotonic: float | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    @property
    def cancelled_monotonic(self) -> float | None:
        with self._lock:
            return self._cancelled_monotonic

    def cancel(self, reason: str) -> bool:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("cancellation reason required")
        now = time.monotonic()
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._cancelled_monotonic = now
            self._event.set()
            return True

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("cancellation wait timeout cannot be negative")
        return self._event.wait(timeout)

    def checkpoint(self) -> None:
        if self._event.is_set():
            raise TaskCancelled(self.reason or "task group cancelled")


@dataclass(frozen=True, slots=True)
class _AnyCancellation(CancellationTokenPort):
    """Cancellation view used only while a provider is admitting a task."""

    first: _CancellationState
    second: _CancellationState

    @property
    def cancelled(self) -> bool:
        return self.first.cancelled or self.second.cancelled

    @property
    def reason(self) -> str | None:
        return self.first.reason or self.second.reason

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("cancellation wait timeout cannot be negative")
        end = None if timeout is None else time.monotonic() + timeout
        while not self.cancelled:
            if end is not None:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self.first.wait(min(0.05, remaining))
            else:
                self.first.wait(0.05)
        return True

    def checkpoint(self) -> None:
        if self.cancelled:
            raise TaskCancelled(self.reason or "task submission cancelled")


@dataclass(frozen=True, slots=True)
class _TaskContext(TaskContextPort):
    _group_id: str
    _task_id: str
    _lane_kind: ExecutionLaneKind
    _group_cancellation: _CancellationState
    _task_cancellation: _CancellationState
    _deadline: Deadline | None
    _deadline_owner: _DeadlineOwner
    _cancel_group: Callable[[str], None]

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def lane_kind(self) -> ExecutionLaneKind:
        return self._lane_kind

    @property
    def deadline(self) -> Deadline | None:
        return self._deadline

    @property
    def cancelled(self) -> bool:
        return self._task_cancellation.cancelled or self._group_cancellation.cancelled

    @property
    def reason(self) -> str | None:
        return self._task_cancellation.reason or self._group_cancellation.reason

    @property
    def remaining_seconds(self) -> float | None:
        return None if self._deadline is None else self._deadline.remaining_seconds

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("task wait timeout cannot be negative")
        if self.cancelled:
            return True

        deadline_limited = False
        resolved_timeout = timeout
        if self._deadline is not None:
            remaining = self._deadline.remaining_seconds
            deadline_limited = timeout is None or remaining <= timeout
            resolved_timeout = remaining if timeout is None else min(timeout, remaining)

        # group.cancel() explicitly cancels every owned task record, so waiting on
        # the task event also wakes for group cancellation without polling.
        if self._task_cancellation.wait(resolved_timeout):
            return True
        if self.cancelled:
            return True

        if deadline_limited and self._deadline is not None:
            # Event.wait/Future.wait may return a scheduler tick before the exact
            # monotonic deadline. Consume the tiny residual interval, then make
            # the task that observed the deadline linearize group cancellation.
            residual = self._deadline.remaining_seconds
            if residual > 0.0 and self._task_cancellation.wait(residual):
                return True
            if self.cancelled:
                return True
            self.checkpoint()
        return False

    def checkpoint(self) -> None:
        self._group_cancellation.checkpoint()
        self._task_cancellation.checkpoint()
        if self._deadline is not None and self._deadline.expired:
            if self._deadline_owner is _DeadlineOwner.GROUP:
                reason = f"task group deadline exceeded: {self._group_id}"
                self._cancel_group(reason)
                self._group_cancellation.checkpoint()
            raise TaskDeadlineExceeded(
                f"task deadline exceeded: {self._group_id}/{self._task_id}"
            )



__all__ = ["_AnyCancellation", "_CancellationState", "_DeadlineOwner", "_TaskContext"]
