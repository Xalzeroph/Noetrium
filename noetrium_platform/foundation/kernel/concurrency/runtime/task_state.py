from __future__ import annotations

from concurrent.futures import CancelledError
from threading import RLock
import time
from typing import Any, Callable

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskState,
    TaskTopologySnapshot,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import ScheduledTaskHandlePort
from .cancellation import _CancellationState, _DeadlineOwner
from .task_records import _RecurringRecord, _TaskRecord, _TERMINAL_STATES


class _TaskStateAuthority:
    """Single logical-state authority for one task group's one-shot and recurring children."""

    def __init__(
        self,
        *,
        group_id: str,
        failure_policy: TaskFailurePolicy,
        group_cancellation: _CancellationState,
        cancel_group: Callable[[str], None],
    ) -> None:
        self._group_id = group_id
        self._failure_policy = failure_policy
        self._group_cancellation = group_cancellation
        self._cancel_group = cancel_group
        self._lock = RLock()
        self._tasks: dict[str, _TaskRecord] = {}
        self._recurring: dict[str, _RecurringRecord] = {}

    @staticmethod
    def _cancel_deadline_handle(handle: ScheduledTaskHandlePort | None) -> None:
        if handle is not None:
            handle.cancel()

    @staticmethod
    def _raw_completed_monotonic(raw: Any | None) -> float | None:
        if raw is None:
            return None
        value = getattr(raw, "completed_monotonic", None)
        return None if value is None else float(value)

    def reserve_task(
        self,
        *,
        task_id: str,
        lane_kind: ExecutionLaneKind,
        lane_id: str | None,
        deadline,
        deadline_owner: _DeadlineOwner,
        failure_scope: TaskFailureScope,
    ) -> _TaskRecord:
        with self._lock:
            if task_id in self._tasks or task_id in self._recurring:
                raise ValueError(f"task id already owned by group: {self._group_id}/{task_id}")
            record = _TaskRecord(
                task_id,
                lane_kind,
                lane_id,
                deadline,
                deadline_owner,
                failure_scope,
            )
            self._tasks[task_id] = record
            return record

    def reserve_recurring(
        self,
        *,
        task_id: str,
        lane_id: str,
        deadline,
        deadline_owner: _DeadlineOwner,
    ) -> _RecurringRecord:
        with self._lock:
            if task_id in self._tasks or task_id in self._recurring:
                raise ValueError(f"task id already owned by group: {self._group_id}/{task_id}")
            record = _RecurringRecord(task_id, lane_id, deadline, deadline_owner)
            self._recurring[task_id] = record
            return record

    def bind_raw(self, record: _TaskRecord, raw: Any, *, mark_running: bool = False) -> None:
        with self._lock:
            current = self._tasks[record.task_id]
            if current is not record:
                raise RuntimeError(f"task record identity drift: {record.task_id}")
            record.raw_handle = raw
            if mark_running and record.state is TaskState.PENDING:
                record.state = TaskState.RUNNING

    def bind_task_deadline(self, record: _TaskRecord, handle: ScheduledTaskHandlePort) -> bool:
        with self._lock:
            if record.state in _TERMINAL_STATES:
                return False
            record.deadline_handle = handle
            return True

    def bind_recurring_deadline(self, record: _RecurringRecord, handle: ScheduledTaskHandlePort) -> bool:
        with self._lock:
            if record.state in {TaskState.FAILED, TaskState.CANCELLED}:
                return False
            record.deadline_handle = handle
            return True

    def bind_recurring_timer(self, record: _RecurringRecord, handle: ScheduledTaskHandlePort) -> bool:
        with self._lock:
            current = self._recurring[record.task_id]
            if current is not record:
                raise RuntimeError(f"recurring task record identity drift: {record.task_id}")
            if record.state in {TaskState.FAILED, TaskState.CANCELLED} or record.cancelled:
                return False
            record.timer_handle = handle
            record.state = TaskState.RUNNING
            return True

    def set_recurring_current(self, record: _RecurringRecord, current: Any) -> None:
        with self._lock:
            if self._recurring.get(record.task_id) is record:
                record.current = current

    def recurring_tick_status(
        self,
        task_id: str,
        *,
        sealed: bool,
        group_cancelled: bool,
    ) -> tuple[_RecurringRecord | None, bool, bool]:
        with self._lock:
            record = self._recurring.get(task_id)
            if record is None:
                return None, True, False
            if sealed or record.cancelled or group_cancelled:
                return record, True, False
            if record.current is not None and not record.current.done():
                return record, True, False
            if record.failure is not None:
                return record, True, False
            expired = record.deadline is not None and record.deadline.expired
            return record, False, expired

    def mark_recurring_execution_cancelled(self, task_id: str) -> None:
        with self._lock:
            record = self._recurring.get(task_id)
            if record is not None and record.state is not TaskState.FAILED:
                record.state = TaskState.CANCELLED

    def mark_recurring_failed(
        self,
        task_id: str,
        failure: BaseException,
        *,
        cancel_reason: str | None = None,
    ) -> bool:
        with self._lock:
            record = self._recurring.get(task_id)
            if record is None or record.state in {TaskState.FAILED, TaskState.CANCELLED}:
                return False
            record.failure = failure
            record.state = TaskState.FAILED
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
            timer_handle = record.timer_handle
            record.timer_handle = None
        self._cancel_deadline_handle(deadline_handle)
        if timer_handle is not None:
            timer_handle.cancel()
        if self._failure_policy is TaskFailurePolicy.FAIL_FAST:
            self._cancel_group(cancel_reason or f"scheduled task failed: {task_id}")
        return True

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if record.state is TaskState.PENDING:
                record.state = TaskState.RUNNING

    def mark_succeeded(self, task_id: str) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if record.state in _TERMINAL_STATES:
                return
            record.state = TaskState.SUCCEEDED
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
        self._cancel_deadline_handle(deadline_handle)

    def mark_cancelled(self, task_id: str, failure: BaseException | None = None) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if record.state in _TERMINAL_STATES:
                return
            record.state = TaskState.CANCELLED
            if failure is not None and record.failure is None:
                record.failure = failure
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
        self._cancel_deadline_handle(deadline_handle)

    def mark_failed(self, task_id: str, failure: BaseException) -> None:
        with self._lock:
            record = self._tasks[task_id]
            if record.state in _TERMINAL_STATES:
                return
            record.state = TaskState.FAILED
            record.failure = failure
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
            should_cancel = (
                record.failure_scope is TaskFailureScope.GROUP
                and self._failure_policy is TaskFailurePolicy.FAIL_FAST
            )
        self._cancel_deadline_handle(deadline_handle)
        if should_cancel:
            self._cancel_group(f"task failed: {task_id}")

    def expire_task(self, task_id: str) -> TaskDeadlineExceeded:
        failure = TaskDeadlineExceeded(f"task deadline exceeded: {self._group_id}/{task_id}")
        with self._lock:
            record = self._tasks[task_id]
            raw = record.raw_handle
            completed = self._raw_completed_monotonic(raw)
            if record.state in _TERMINAL_STATES:
                return record.failure if isinstance(record.failure, TaskDeadlineExceeded) else failure
            if (
                completed is not None
                and record.deadline is not None
                and completed <= record.deadline.monotonic_deadline
            ):
                should_sync = True
                lane_kind = record.lane_kind
                should_cancel_group = False
            else:
                should_sync = False
                record.failure = failure
                record.state = TaskState.FAILED
                record.deadline_handle = None
                lane_kind = record.lane_kind
                should_cancel_group = (
                    record.failure_scope is TaskFailureScope.GROUP
                    and self._failure_policy is TaskFailurePolicy.FAIL_FAST
                )
        if should_sync:
            self.sync_terminal_from_raw(task_id)
            return failure
        if lane_kind is not ExecutionLaneKind.CPU:
            record.cancellation.cancel(f"task deadline exceeded: {task_id}")
        if raw is not None:
            raw.cancel()
        if should_cancel_group:
            self._cancel_group(f"task deadline exceeded: {task_id}")
        return failure

    def expire_recurring(self, task_id: str) -> None:
        failure = TaskDeadlineExceeded(
            f"scheduled task deadline exceeded: {self._group_id}/{task_id}"
        )
        with self._lock:
            record = self._recurring.get(task_id)
            if record is None or record.state in {TaskState.FAILED, TaskState.CANCELLED}:
                return
            record.failure = failure
            record.state = TaskState.FAILED
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
            current = record.current
            timer_handle = record.timer_handle
            should_cancel_group = self._failure_policy is TaskFailurePolicy.FAIL_FAST
        self._cancel_deadline_handle(deadline_handle)
        record.cancellation.cancel(f"scheduled task deadline exceeded: {task_id}")
        if current is not None:
            current.cancel()
        if timer_handle is not None:
            timer_handle.cancel()
        if should_cancel_group:
            self._cancel_group(f"scheduled task deadline exceeded: {task_id}")

    def sync_terminal_from_raw(self, task_id: str) -> None:
        """Reconcile one logical task record with its provider handle.

        Algorithm-Complexity: O(1)
        Algorithm-Rationale: The method performs bounded lookups, state checks, and one provider-result probe for exactly one task without scanning group collections.
        """
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record.raw_handle is None:
                return
            raw = record.raw_handle
            if not raw.done():
                if record.state is TaskState.PENDING and hasattr(raw, "running") and raw.running():
                    record.state = TaskState.RUNNING
                return
            completed = self._raw_completed_monotonic(raw) or time.monotonic()
            deadline = record.deadline
            deadline_missed = (
                deadline is not None
                and record.deadline_owner is _DeadlineOwner.TASK
                and completed > deadline.monotonic_deadline
            )
            already_terminal = record.state in _TERMINAL_STATES
            predetermined_failure = record.failure
        if already_terminal:
            return
        if deadline_missed:
            self.mark_failed(
                task_id,
                predetermined_failure
                if isinstance(predetermined_failure, TaskDeadlineExceeded)
                else TaskDeadlineExceeded(f"task deadline exceeded: {self._group_id}/{task_id}"),
            )
            return
        try:
            raw.result(timeout=0)
        except CancelledError as exc:
            if isinstance(predetermined_failure, TaskDeadlineExceeded):
                self.mark_failed(task_id, predetermined_failure)
            else:
                self.mark_cancelled(task_id, exc)
        except TaskCancelled as exc:
            self.mark_cancelled(task_id, exc)
        except TaskDeadlineExceeded as exc:
            if record.deadline_owner is _DeadlineOwner.GROUP:
                reason = f"task group deadline exceeded: {self._group_id}"
                self._cancel_group(reason)
                self.mark_cancelled(
                    task_id,
                    TaskCancelled(self._group_cancellation.reason or reason),
                )
            else:
                self.mark_failed(task_id, exc)
        except BaseException as exc:
            self.mark_failed(task_id, exc)
        else:
            if predetermined_failure is not None:
                self.mark_failed(task_id, predetermined_failure)
                return
            cancellation_times = tuple(
                value
                for value in (
                    record.cancellation.cancelled_monotonic,
                    self._group_cancellation.cancelled_monotonic,
                )
                if value is not None
            )
            if cancellation_times and min(cancellation_times) <= completed:
                self.mark_cancelled(task_id)
            else:
                self.mark_succeeded(task_id)

    def task_state(self, task_id: str) -> TaskState:
        self.sync_terminal_from_raw(task_id)
        with self._lock:
            return self._tasks[task_id].state

    def task_failure(self, task_id: str) -> BaseException | None:
        self.sync_terminal_from_raw(task_id)
        with self._lock:
            return self._tasks[task_id].failure

    def task_terminal(self, task_id: str) -> bool:
        self.sync_terminal_from_raw(task_id)
        with self._lock:
            return self._tasks[task_id].state in _TERMINAL_STATES

    def cancel_task(self, task_id: str, *, reason: str = "task cancelled") -> bool:
        with self._lock:
            record = self._tasks[task_id]
            raw = record.raw_handle
            terminal = record.state in _TERMINAL_STATES
        if terminal:
            return False
        cooperative = record.cancellation.cancel(reason)
        raw_cancelled = False if raw is None else bool(raw.cancel())
        self.mark_cancelled(task_id)
        return cooperative or raw_cancelled

    def cancel_recurring(self, task_id: str) -> None:
        with self._lock:
            record = self._recurring.get(task_id)
            if record is None:
                return
            record.cancelled = True
            record.cancellation.cancel(f"scheduled task cancelled: {task_id}")
            if record.state is not TaskState.FAILED:
                record.state = TaskState.CANCELLED
            current = record.current
            deadline_handle = record.deadline_handle
            record.deadline_handle = None
            timer_handle = record.timer_handle
        self._cancel_deadline_handle(deadline_handle)
        if current is not None:
            current.cancel()
        if timer_handle is not None:
            timer_handle.cancel()

    def cancel_all(self, *, reason: str) -> None:
        with self._lock:
            recurring_ids = tuple(self._recurring)
            task_ids = tuple(self._tasks)
        for task_id in recurring_ids:
            self.cancel_recurring(task_id)
        for task_id in task_ids:
            self.cancel_task(task_id, reason=reason)

    def cancel_all_recurring(self) -> None:
        with self._lock:
            recurring_ids = tuple(self._recurring)
        for task_id in recurring_ids:
            self.cancel_recurring(task_id)

    def recurring_failure(self, task_id: str) -> BaseException | None:
        with self._lock:
            record = self._recurring.get(task_id)
            return None if record is None else record.failure

    def recurring_outcome(self, task_id: str) -> tuple[TaskState, BaseException | None, Any | None]:
        with self._lock:
            record = self._recurring[task_id]
            return record.state, record.failure, record.current

    def task_records(self) -> tuple[_TaskRecord, ...]:
        with self._lock:
            return tuple(self._tasks.values())

    def recurring_records(self) -> tuple[_RecurringRecord, ...]:
        with self._lock:
            return tuple(self._recurring.values())

    def task_outcome(
        self, task_id: str
    ) -> tuple[TaskState, BaseException | None, TaskFailureScope]:
        self.sync_terminal_from_raw(task_id)
        with self._lock:
            record = self._tasks[task_id]
            return record.state, record.failure, record.failure_scope

    def failures(self) -> tuple[BaseException, ...]:
        with self._lock:
            task_ids = tuple(self._tasks)
        for task_id in task_ids:
            self.sync_terminal_from_raw(task_id)
        with self._lock:
            return tuple(
                record.failure
                for record in (*self._tasks.values(), *self._recurring.values())
                if (
                    record.failure is not None
                    and record.state is TaskState.FAILED
                    and getattr(record, "failure_scope", TaskFailureScope.GROUP)
                    is TaskFailureScope.GROUP
                )
            )

    @staticmethod
    def _execution_done(record: _TaskRecord) -> bool:
        raw = record.raw_handle
        if raw is None:
            return record.state in _TERMINAL_STATES
        return bool(raw.done())

    def topology(self) -> tuple[TaskTopologySnapshot, ...]:
        with self._lock:
            task_ids = tuple(self._tasks)
        for task_id in task_ids:
            self.sync_terminal_from_raw(task_id)
        with self._lock:
            tasks = [
                TaskTopologySnapshot(
                    group_id=self._group_id,
                    task_id=record.task_id,
                    lane_kind=record.lane_kind,
                    lane_id=record.lane_id,
                    state=record.state,
                    execution_done=self._execution_done(record),
                    deadline_monotonic=None
                    if record.deadline is None
                    else record.deadline.monotonic_deadline,
                    failure_type=None if record.failure is None else type(record.failure).__name__,
                    failure_scope=record.failure_scope,
                )
                for record in self._tasks.values()
            ]
            tasks.extend(
                TaskTopologySnapshot(
                    group_id=self._group_id,
                    task_id=record.task_id,
                    lane_kind=ExecutionLaneKind.SERIAL,
                    lane_id=record.lane_id,
                    state=record.state,
                    execution_done=(
                        record.state in _TERMINAL_STATES
                        and (record.current is None or bool(record.current.done()))
                    ),
                    deadline_monotonic=None
                    if record.deadline is None
                    else record.deadline.monotonic_deadline,
                    failure_type=None if record.failure is None else type(record.failure).__name__,
                )
                for record in self._recurring.values()
            )
        return tuple(sorted(tasks, key=lambda item: item.task_id))

    def all_execution_done(self) -> bool:
        with self._lock:
            tasks = tuple(self._tasks.values())
            recurring = tuple(self._recurring.values())
        return all(self._execution_done(record) for record in tasks) and all(
            record.current is None or bool(record.current.done()) for record in recurring
        )


__all__ = ["_TaskStateAuthority"]
