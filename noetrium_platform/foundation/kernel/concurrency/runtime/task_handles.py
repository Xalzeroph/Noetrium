from __future__ import annotations

from concurrent.futures import CancelledError
from typing import Generic, TYPE_CHECKING, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskState,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import ScheduledTaskHandlePort, TaskHandlePort
from .cancellation import _DeadlineOwner
from .task_records import _RecurringRecord, _TaskRecord, _TERMINAL_STATES

if TYPE_CHECKING:
    from .task_group import StructuredTaskGroup

T = TypeVar("T")

class _OwnedTaskHandle(Generic[T], TaskHandlePort[T]):
    def __init__(self, group: "StructuredTaskGroup", record: _TaskRecord) -> None:
        self._group = group
        self._record = record

    @property
    def task_id(self) -> str:
        return self._record.task_id

    @property
    def lane_kind(self) -> ExecutionLaneKind:
        return self._record.lane_kind

    @property
    def state(self) -> TaskState:
        return self._group._task_state(self._record.task_id)

    def done(self) -> bool:
        # Logical outcome and physical execution are intentionally distinct.  A
        # non-preemptive CPU child can be deadline-failed while its worker is still
        # running; callers that need structured convergence must use wait/close.
        raw = self._record.raw_handle
        return self.state in _TERMINAL_STATES if raw is None else bool(raw.done())

    def cancel(self) -> bool:
        return self._group._cancel_task(self._record.task_id)

    def result(self, timeout: float | None = None) -> T:
        raw = self._record.raw_handle
        if raw is None:
            failure = self._group._task_failure(self._record.task_id)
            if failure is not None:
                raise failure
            raise RuntimeError(f"task was not submitted: {self._record.task_id}")

        # A deadline is a logical outcome even when a CPU child cannot be
        # preempted.  Surface that outcome immediately; scope close still joins the
        # underlying worker before claiming clean structured convergence.
        failure = self._group._task_failure(self._record.task_id)
        if isinstance(failure, TaskDeadlineExceeded):
            if self._record.deadline_owner is _DeadlineOwner.GROUP:
                reason = f"task group deadline exceeded: {self._group.group_id}"
                self._group.cancel(reason)
                raise TaskCancelled(self._group.cancellation.reason or reason) from failure
            raise failure

        deadline_remaining = (
            None if self._record.deadline is None else self._record.deadline.remaining_seconds
        )
        deadline_limited = (
            deadline_remaining is not None
            and (timeout is None or deadline_remaining <= timeout)
        )
        resolved_timeout = self._group._bounded_wait_timeout(self._record.deadline, timeout)
        try:
            value = raw.result(timeout=resolved_timeout)
        except CancelledError as exc:
            self._group._sync_terminal_from_raw(self._record.task_id)
            failure = self._group._task_failure(self._record.task_id)
            if isinstance(failure, TaskDeadlineExceeded):
                raise failure from exc
            raise TaskCancelled(
                self._record.cancellation.reason
                or self._group.cancellation.reason
                or f"task cancelled: {self._record.task_id}"
            ) from exc
        except TimeoutError as exc:
            if self._record.deadline is not None and deadline_limited:
                # Future.result may return a few scheduler ticks before the exact
                # monotonic deadline.  Finish the tiny residual interval before
                # converting the bounded wait into the logical deadline outcome.
                remaining = self._record.deadline.remaining_seconds
                if remaining > 0.0:
                    try:
                        value = raw.result(timeout=remaining)
                    except CancelledError as cancelled:
                        self._group._sync_terminal_from_raw(self._record.task_id)
                        failure = self._group._task_failure(self._record.task_id)
                        if isinstance(failure, TaskDeadlineExceeded):
                            raise failure from cancelled
                        raise TaskCancelled(
                            self._record.cancellation.reason
                            or self._group.cancellation.reason
                            or f"task cancelled: {self._record.task_id}"
                        ) from cancelled
                    except TimeoutError:
                        pass
                    else:
                        self._group._sync_terminal_from_raw(self._record.task_id)
                        state = self._group._task_state(self._record.task_id)
                        failure = self._group._task_failure(self._record.task_id)
                        if state is TaskState.FAILED and failure is not None:
                            raise failure
                        if state is TaskState.CANCELLED:
                            raise TaskCancelled(
                                self._record.cancellation.reason
                                or self._group.cancellation.reason
                                or f"task cancelled: {self._record.task_id}"
                            )
                        return value
                if self._record.deadline_owner is _DeadlineOwner.GROUP:
                    self._group.cancel(f"task group deadline exceeded: {self._group.group_id}")
                    raise TaskCancelled(
                        self._group.cancellation.reason or "task group deadline exceeded"
                    ) from exc
                failure = self._group._expire_task(self._record.task_id)
                raise failure from exc
            raise
        except BaseException as exc:
            self._group._sync_terminal_from_raw(self._record.task_id)
            failure = self._group._task_failure(self._record.task_id)
            if failure is not None and failure is not exc:
                raise failure from exc
            raise

        self._group._sync_terminal_from_raw(self._record.task_id)
        state = self._group._task_state(self._record.task_id)
        failure = self._group._task_failure(self._record.task_id)
        if state is TaskState.FAILED and failure is not None:
            raise failure
        if state is TaskState.CANCELLED:
            raise TaskCancelled(
                self._record.cancellation.reason
                or self._group.cancellation.reason
                or f"task cancelled: {self._record.task_id}"
            )
        return value



class _OwnedScheduledHandle(ScheduledTaskHandlePort):
    def __init__(
        self,
        group: "StructuredTaskGroup",
        record: _RecurringRecord,
        timer_handle: ScheduledTaskHandlePort,
    ) -> None:
        self._group = group
        self._record = record
        self._timer_handle = timer_handle

    @property
    def task_id(self) -> str:
        return self._record.task_id

    def cancel(self) -> None:
        # Task-state authority owns both logical cancellation and the provider timer.
        self._group._cancel_recurring(self._record.task_id)

    def assert_healthy(self) -> None:
        self._timer_handle.assert_healthy()
        failure = self._group._recurring_failure(self._record.task_id)
        if failure is not None:
            raise RuntimeError(
                f"scheduled task failed: {self._group.group_id}/{self._record.task_id}: "
                f"{type(failure).__name__}: {failure}"
            ) from failure



__all__ = ["_OwnedScheduledHandle", "_OwnedTaskHandle"]
