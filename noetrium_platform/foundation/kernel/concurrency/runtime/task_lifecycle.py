from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from threading import Condition, Event, RLock
from typing import Iterator

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskCancelled
from noetrium_platform.foundation.kernel.concurrency.api.ports import CancellationTokenPort, ScheduledTaskHandlePort


class _CloseDisposition(Enum):
    COMPLETE = "complete"
    WAIT = "wait"
    LEADER = "leader"


@dataclass(frozen=True, slots=True)
class _LifecycleSnapshot:
    closing: bool
    closed: bool
    converged: bool
    close_failure: BaseException | None


class _TaskGroupLifecycleAuthority:
    """Linearization authority for submissions, close leadership and group deadline ownership."""

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._active_submissions = 0
        self._closing = False
        self._closed = False
        self._converged = False
        self._close_complete = Event()
        self._close_failure: BaseException | None = None
        self._group_deadline_handle: ScheduledTaskHandlePort | None = None

    @contextmanager
    def submission_scope(
        self,
        *,
        group_id: str,
        cancellation: CancellationTokenPort,
    ) -> Iterator[None]:
        with self._condition:
            if self._closing or self._closed:
                raise RuntimeError(f"task group closed: {group_id}")
            if cancellation.cancelled:
                raise TaskCancelled(cancellation.reason or "task group cancelled")
            self._active_submissions += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_submissions -= 1
                if self._active_submissions < 0:
                    raise RuntimeError("task group submission accounting underflow")
                self._condition.notify_all()

    def install_group_deadline(self, handle: ScheduledTaskHandlePort) -> None:
        with self._condition:
            if self._group_deadline_handle is not None:
                raise RuntimeError("task group deadline already installed")
            self._group_deadline_handle = handle

    def take_group_deadline(self) -> ScheduledTaskHandlePort | None:
        with self._condition:
            handle = self._group_deadline_handle
            self._group_deadline_handle = None
            return handle

    @property
    def sealed(self) -> bool:
        with self._condition:
            return self._closing or self._closed

    def begin_close(self) -> tuple[_CloseDisposition, BaseException | None]:
        with self._condition:
            if self._closed and self._converged:
                return _CloseDisposition.COMPLETE, self._close_failure
            if self._closing:
                return _CloseDisposition.WAIT, None
            self._closing = True
            self._closed = True
            self._close_failure = None
            self._close_complete.clear()
            return _CloseDisposition.LEADER, None

    def wait_for_existing_close(self, *, deadline: Deadline, group_id: str) -> BaseException | None:
        if not self._close_complete.wait(deadline.remaining_seconds):
            raise TimeoutError(f"task group close did not converge: {group_id}")
        with self._condition:
            return self._close_failure

    def wait_for_submissions(self, *, deadline: Deadline, group_id: str) -> None:
        """Wait until every in-flight submission scope has left.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: At most one constant-time counter/deadline check is required per submission-completion wake-up before the active count reaches zero.
        """
        with self._condition:
            while self._active_submissions:
                remaining = deadline.remaining_seconds
                if remaining <= 0:
                    raise TimeoutError(
                        f"task group submissions did not quiesce before deadline: {group_id}"
                    )
                self._condition.wait(remaining)

    def complete_close(self, *, failure: BaseException | None, converged: bool) -> None:
        with self._condition:
            self._close_failure = failure
            self._converged = bool(converged)
            self._closing = False
            self._condition.notify_all()
        self._close_complete.set()

    def snapshot(self) -> _LifecycleSnapshot:
        with self._condition:
            return _LifecycleSnapshot(
                closing=self._closing,
                closed=self._closed,
                converged=self._converged,
                close_failure=self._close_failure,
            )


__all__ = ["_CloseDisposition", "_LifecycleSnapshot", "_TaskGroupLifecycleAuthority"]
