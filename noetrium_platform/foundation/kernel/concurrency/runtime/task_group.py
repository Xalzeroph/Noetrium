from __future__ import annotations

from contextlib import contextmanager
import time
from typing import Any, Callable, Iterator, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    SerialMailboxPolicy,
    SerialMailboxRejected,
    Deadline,
    ExecutionLaneKind,
    ExecutionPermitRejected,
    ExecutionSpec,
    ScheduledTaskSpec,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskGroupTopologySnapshot,
    TaskState,
    SerialActorPort,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import (
    CancellationTokenPort,
    ExecutionAuthorityProviderPort,
    ScheduledTaskHandlePort,
    TaskHandlePort,
    TimerSchedulerProviderPort,
)
from .actor import SerialActor
from .cancellation import _AnyCancellation, _CancellationState, _DeadlineOwner, _TaskContext
from .task_handles import _OwnedScheduledHandle, _OwnedTaskHandle
from .task_lifecycle import _CloseDisposition, _TaskGroupLifecycleAuthority
from .task_records import _RecurringRecord, _TaskRecord
from .task_state import _TaskStateAuthority

T = TypeVar("T")


class StructuredTaskGroup:
    """Owned task scope with explicit submission, cancellation and deadline authority.

    Blocking-I/O and serial tasks receive ``TaskContextPort`` as their first
    argument. CPU tasks are process-isolated pure functions and deliberately do
    not receive a context: running process work is non-preemptive.  Logical task
    outcome can therefore become FAILED/CANCELLED before physical execution ends;
    ``TaskTopologySnapshot.execution_done`` and ``wait/close`` make that distinction
    explicit rather than pretending a timed-out process disappeared.
    """

    def __init__(
        self,
        *,
        group_id: str,
        execution: ExecutionAuthorityProviderPort,
        timers: TimerSchedulerProviderPort,
        default_queue_capacity: int,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
        shutdown_timeout_seconds: float = 30.0,
        on_close: Callable[[str, Deadline], None] | None = None,
    ) -> None:
        group_id = str(group_id).strip()
        if not group_id:
            raise ValueError("task group id required")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("task group shutdown timeout must be positive")
        self._group_id = group_id
        self._execution = execution
        self._timers = timers
        self._default_queue_capacity = int(default_queue_capacity)
        self._deadline = deadline
        self._failure_policy = failure_policy
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._on_close = on_close
        self._cancellation = _CancellationState()
        self._submission_cancellation = _CancellationState()
        self._provider_submission_cancellation = _AnyCancellation(
            self._cancellation,
            self._submission_cancellation,
        )
        self._lifecycle = _TaskGroupLifecycleAuthority()
        self._state = _TaskStateAuthority(
            group_id=group_id,
            failure_policy=failure_policy,
            group_cancellation=self._cancellation,
            cancel_group=self.cancel,
        )
        if deadline is not None:
            if deadline.expired:
                raise TaskDeadlineExceeded(f"task group deadline already expired: {group_id}")
            handle = self._timers.schedule_once(
                f"task-group-deadline:{group_id}",
                deadline.remaining_seconds,
                lambda: self.cancel(f"task group deadline exceeded: {group_id}"),
            )
            self._lifecycle.install_group_deadline(handle)

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def cancellation(self) -> CancellationTokenPort:
        return self._cancellation

    def open_serial_actor(
        self,
        actor_id: str,
        *,
        lane_id: str | None = None,
        capacity: int | None = None,
    ) -> SerialActorPort:
        resolved_actor_id = str(actor_id).strip()
        if not resolved_actor_id:
            raise ValueError("serial actor id required")
        resolved_lane_id = resolved_actor_id if lane_id is None else str(lane_id).strip()
        # Resolve immediately so actor ownership/capacity conflicts are detected at
        # composition time rather than on the first mutation.
        self._execution.ensure_serial_lane(self._group_id, resolved_lane_id, capacity)
        return SerialActor(
            self,
            resolved_actor_id,
            lane_id=resolved_lane_id,
            capacity=capacity,
        )

    @contextmanager
    def _submission_scope(self) -> Iterator[None]:
        with self._lifecycle.submission_scope(
            group_id=self._group_id,
            cancellation=self._cancellation,
        ):
            yield

    def _effective_deadline(
        self, child: Deadline | None
    ) -> tuple[Deadline | None, _DeadlineOwner]:
        """Resolve exactly one deadline owner for a child.

        The group deadline is enforced once by the group timer. Children inheriting
        it never register their own timer. A stricter child deadline is task-owned
        and receives one independent timer. This prevents duplicate deadline
        authorities from racing to choose incompatible terminal causes.
        """

        if self._deadline is None:
            return (child, _DeadlineOwner.TASK) if child is not None else (None, _DeadlineOwner.NONE)
        if child is None or self._deadline.monotonic_deadline <= child.monotonic_deadline:
            return self._deadline, _DeadlineOwner.GROUP
        return child, _DeadlineOwner.TASK

    def _reserve_task(
        self,
        task_id: str,
        lane_kind: ExecutionLaneKind,
        lane_id: str | None,
        deadline: Deadline | None,
        failure_scope: TaskFailureScope,
    ) -> _TaskRecord:
        task_id = str(task_id).strip()
        if not task_id:
            raise ValueError("task id required")
        effective, deadline_owner = self._effective_deadline(deadline)
        record = self._state.reserve_task(
            task_id=task_id,
            lane_kind=lane_kind,
            lane_id=lane_id,
            deadline=effective,
            deadline_owner=deadline_owner,
            failure_scope=failure_scope,
        )
        if effective is not None and effective.expired:
            if deadline_owner is _DeadlineOwner.GROUP:
                reason = f"task group deadline exceeded: {self._group_id}"
                self.cancel(reason)
                failure = TaskCancelled(self._cancellation.reason or reason)
                self._mark_cancelled(task_id, failure)
                raise failure
            failure = TaskDeadlineExceeded(
                f"task deadline already expired: {self._group_id}/{task_id}"
            )
            self._mark_failed(task_id, failure)
            raise failure
        return record

    def _submit_contextual(
        self,
        *,
        spec: ExecutionSpec,
        record: _TaskRecord,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> TaskHandlePort[T]:
        context = _TaskContext(
            self._group_id,
            record.task_id,
            record.lane_kind,
            self._cancellation,
            record.cancellation,
            record.deadline,
            record.deadline_owner,
            self.cancel,
        )

        def invoke() -> T:
            self._mark_running(record.task_id)
            context.checkpoint()
            value = fn(context, *args, **kwargs)
            context.checkpoint()
            return value

        try:
            raw = self._execution.submit(
                self._group_id,
                spec,
                invoke,
                deadline=record.deadline,
                cancellation=self._provider_submission_cancellation,
            )
        except TaskCancelled as exc:
            self._mark_cancelled(record.task_id, exc)
            raise
        except ExecutionPermitRejected:
            self._mark_cancelled(
                record.task_id,
                TaskCancelled(f"execution permit rejected: {self._group_id}/{record.task_id}"),
            )
            raise
        except SerialMailboxRejected:
            self._mark_cancelled(
                record.task_id,
                TaskCancelled(f"execution permit rejected: {self._group_id}/{record.task_id}"),
            )
            raise
        except BaseException as exc:
            failure = self._normalize_submission_failure(record, exc)
            if isinstance(failure, TaskCancelled):
                self._mark_cancelled(record.task_id, failure)
            else:
                self._mark_failed(record.task_id, failure)
            if failure is exc:
                raise
            raise failure from exc
        self._state.bind_raw(record, raw)
        if hasattr(raw, "add_done_callback"):
            raw.add_done_callback(lambda _handle: self._sync_terminal_from_raw(record.task_id))
        self._arm_task_deadline(record)
        if self._cancellation.cancelled or self._submission_cancellation.cancelled:
            self._cancel_task(
                record.task_id,
                reason=self._cancellation.reason or "task group closing",
            )
        return _OwnedTaskHandle(self, record)

    def submit(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        """Submit through the single owner-aware execution port.

        Blocking-I/O and SERIAL callables receive ``TaskContextPort`` as their
        first argument. CPU callables remain pure process-callable functions and
        receive only the explicit arguments. The execution class is therefore a
        property of the request, not a different executor API.
        """

        if spec.lane_kind is ExecutionLaneKind.BLOCKING_IO:
            return self._submit_blocking(spec, fn, *args, deadline=deadline, **kwargs)
        if spec.lane_kind is ExecutionLaneKind.ASYNC_IO:
            return self._submit_async_io(spec, fn, *args, deadline=deadline, **kwargs)
        if spec.lane_kind is ExecutionLaneKind.CPU:
            return self._submit_cpu(spec, fn, *args, deadline=deadline, **kwargs)
        if spec.lane_kind is ExecutionLaneKind.SERIAL:
            return self._submit_serial(spec, fn, *args, deadline=deadline, **kwargs)
        raise ValueError(f"unsupported execution lane: {spec.lane_kind}")

    def _submit_blocking(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        with self._submission_scope():
            record = self._reserve_task(spec.task_id, ExecutionLaneKind.BLOCKING_IO, None, deadline, spec.failure_scope)
            return self._submit_contextual(
                spec=spec,
                record=record,
                fn=fn,
                args=args,
                kwargs=kwargs,
            )

    def _submit_async_io(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        with self._submission_scope():
            record = self._reserve_task(spec.task_id, ExecutionLaneKind.ASYNC_IO, None, deadline, spec.failure_scope)
            context = _TaskContext(
                self._group_id,
                record.task_id,
                record.lane_kind,
                self._cancellation,
                record.cancellation,
                record.deadline,
                record.deadline_owner,
                self.cancel,
            )

            async def invoke() -> T:
                # Coroutine entry is the running-state authority: the
                # run_coroutine_threadsafe proxy Future does not report running().
                self._mark_running(record.task_id)
                context.checkpoint()
                value = fn(context, *args, **kwargs)
                import inspect
                if not inspect.isawaitable(value):
                    raise TypeError("ASYNC_IO task callable must return an awaitable")
                result = await value
                context.checkpoint()
                return result

            try:
                raw = self._execution.submit(
                    self._group_id,
                    spec,
                    invoke,
                    deadline=record.deadline,
                    cancellation=self._provider_submission_cancellation,
                )
            except TaskCancelled as exc:
                self._mark_cancelled(record.task_id, exc)
                raise
            except ExecutionPermitRejected:
                self._mark_cancelled(
                    record.task_id,
                    TaskCancelled(f"execution permit rejected: {self._group_id}/{record.task_id}"),
                )
                raise
            except BaseException as exc:
                failure = self._normalize_submission_failure(record, exc)
                if isinstance(failure, TaskCancelled):
                    self._mark_cancelled(record.task_id, failure)
                else:
                    self._mark_failed(record.task_id, failure)
                if failure is exc:
                    raise
                raise failure from exc
            self._state.bind_raw(record, raw)
            if hasattr(raw, "add_done_callback"):
                raw.add_done_callback(lambda _handle: self._sync_terminal_from_raw(record.task_id))
            self._arm_task_deadline(record)
            if self._cancellation.cancelled or self._submission_cancellation.cancelled:
                self._cancel_task(
                    record.task_id,
                    reason=self._cancellation.reason or "task group closing",
                )
            return _OwnedTaskHandle(self, record)

    def _submit_serial(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        with self._submission_scope():
            lane = self._execution.ensure_serial_lane(self._group_id, spec.lane_id or "", spec.capacity)
            record = self._reserve_task(spec.task_id, ExecutionLaneKind.SERIAL, lane.lane_id, deadline, spec.failure_scope)
            return self._submit_contextual(
                spec=spec,
                record=record,
                fn=fn,
                args=args,
                kwargs=kwargs,
            )

    def _submit_cpu(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        with self._submission_scope():
            record = self._reserve_task(spec.task_id, ExecutionLaneKind.CPU, None, deadline, spec.failure_scope)
            try:
                raw = self._execution.submit(
                    self._group_id,
                    spec,
                    fn,
                    *args,
                    deadline=record.deadline,
                    cancellation=self._provider_submission_cancellation,
                    **kwargs,
                )
            except TaskCancelled as exc:
                self._mark_cancelled(record.task_id, exc)
                raise
            except ExecutionPermitRejected:
                self._mark_cancelled(
                    record.task_id,
                    TaskCancelled(f"execution permit rejected: {self._group_id}/{record.task_id}"),
                )
                raise
            except BaseException as exc:
                failure = self._normalize_submission_failure(record, exc)
                if isinstance(failure, TaskCancelled):
                    self._mark_cancelled(record.task_id, failure)
                else:
                    self._mark_failed(record.task_id, failure)
                if failure is exc:
                    raise
                raise failure from exc
            self._state.bind_raw(record, raw, mark_running=True)
            if hasattr(raw, "add_done_callback"):
                raw.add_done_callback(lambda _handle: self._sync_terminal_from_raw(record.task_id))
            self._arm_task_deadline(record)
            if self._cancellation.cancelled or self._submission_cancellation.cancelled:
                self._cancel_task(
                    record.task_id,
                    reason=self._cancellation.reason or "task group closing",
                )
            return _OwnedTaskHandle(self, record)

    def _schedule_serial_fixed_delay(
        self,
        lane_id: str,
        spec: ScheduledTaskSpec,
        fn: Callable[..., Any],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        capacity: int | None = None,
        **kwargs: Any,
    ) -> ScheduledTaskHandlePort:
        with self._submission_scope():
            lane = self._execution.ensure_serial_lane(self._group_id, lane_id, capacity)
            effective, deadline_owner = self._effective_deadline(deadline)
            record = self._state.reserve_recurring(
                task_id=spec.task_id,
                lane_id=lane.lane_id,
                deadline=effective,
                deadline_owner=deadline_owner,
            )

            if effective is not None and effective.expired:
                if deadline_owner is _DeadlineOwner.GROUP:
                    reason = f"task group deadline exceeded: {self._group_id}"
                    self.cancel(reason)
                    self._cancel_recurring(record.task_id)
                    raise TaskCancelled(self._cancellation.reason or reason)
                self._expire_recurring(record.task_id)
                raise TaskDeadlineExceeded(
                    f"scheduled task deadline already expired: {self._group_id}/{record.task_id}"
                )

            def tick() -> None:
                current_record, skip, expired = self._state.recurring_tick_status(
                    record.task_id,
                    sealed=self._lifecycle.sealed,
                    group_cancelled=self._cancellation.cancelled,
                )
                if current_record is None or skip:
                    return
                if expired:
                    if current_record.deadline_owner is _DeadlineOwner.GROUP:
                        self.cancel(f"task group deadline exceeded: {self._group_id}")
                    else:
                        self._expire_recurring(current_record.task_id)
                    return
                context = _TaskContext(
                    self._group_id,
                    current_record.task_id,
                    ExecutionLaneKind.SERIAL,
                    self._cancellation,
                    current_record.cancellation,
                    current_record.deadline,
                    current_record.deadline_owner,
                    self.cancel,
                )

                def invoke() -> Any:
                    context.checkpoint()
                    value = fn(context, *args, **kwargs)
                    context.checkpoint()
                    return value

                try:
                    current = self._execution.submit(
                        self._group_id,
                        ExecutionSpec(
                            task_id=f"heartbeat-tick:{current_record.task_id}",
                            lane_kind=ExecutionLaneKind.SERIAL,
                            lane_id=current_record.lane_id,
                            capacity=capacity,
                            mailbox_policy=SerialMailboxPolicy.REJECT,
                        ),
                        invoke,
                        deadline=current_record.deadline,
                        cancellation=context,
                    )
                except SerialMailboxRejected:
                    return
                except TaskCancelled:
                    self._state.mark_recurring_execution_cancelled(current_record.task_id)
                    return
                except BaseException as exc:
                    self._state.mark_recurring_failed(
                        current_record.task_id,
                        exc,
                        cancel_reason=f"scheduled task submission failed: {current_record.task_id}",
                    )
                    return

                def on_done(_handle: Any) -> None:
                    try:
                        _handle.result(timeout=0)
                    except TaskCancelled:
                        self._state.mark_recurring_execution_cancelled(current_record.task_id)
                    except BaseException as exc:
                        self._state.mark_recurring_failed(
                            current_record.task_id,
                            exc,
                            cancel_reason=f"scheduled task failed: {current_record.task_id}",
                        )

                if hasattr(current, "add_done_callback"):
                    current.add_done_callback(on_done)
                self._state.set_recurring_current(current_record, current)

            try:
                provider_spec = ScheduledTaskSpec(
                    task_id=f"{self._group_id}/{spec.task_id}",
                    interval_seconds=spec.interval_seconds,
                    initial_delay_seconds=spec.initial_delay_seconds,
                )
                timer_handle = self._timers.schedule_fixed_delay(provider_spec, tick)
            except BaseException as exc:
                self._state.mark_recurring_failed(
                    record.task_id,
                    exc,
                    cancel_reason=f"scheduled task registration failed: {record.task_id}",
                )
                raise
            owned = _OwnedScheduledHandle(self, record, timer_handle)
            if not self._state.bind_recurring_timer(record, timer_handle):
                timer_handle.cancel()
            self._arm_recurring_deadline(record)
            if (
                self._cancellation.cancelled
                or self._submission_cancellation.cancelled
                or self._lifecycle.sealed
            ):
                owned.cancel()
            return owned

    def _normalize_submission_failure(self, record: _TaskRecord, failure: BaseException) -> BaseException:
        if isinstance(failure, TimeoutError) and record.deadline is not None and record.deadline.expired:
            if record.deadline_owner is _DeadlineOwner.GROUP:
                self.cancel(f"task group deadline exceeded: {self._group_id}")
                return TaskCancelled(self._cancellation.reason or "task group deadline exceeded")
            return TaskDeadlineExceeded(f"task deadline exceeded during submission: {record.task_id}")
        return failure


    def _arm_task_deadline(self, record: _TaskRecord) -> None:
        if record.deadline is None or record.deadline_owner is not _DeadlineOwner.TASK:
            return
        self._sync_terminal_from_raw(record.task_id)
        if self._state.task_terminal(record.task_id):
            return
        remaining = record.deadline.remaining_seconds
        if remaining <= 0:
            self._expire_task(record.task_id)
            return
        try:
            handle = self._timers.schedule_once(
                f"task-deadline:{self._group_id}/{record.task_id}",
                remaining,
                lambda: self._expire_task(record.task_id),
            )
        except BaseException as exc:
            self._mark_failed(record.task_id, exc)
            raise
        if not self._state.bind_task_deadline(record, handle):
            handle.cancel()

    def _arm_recurring_deadline(self, record: _RecurringRecord) -> None:
        if record.deadline is None or record.deadline_owner is not _DeadlineOwner.TASK:
            return
        remaining = record.deadline.remaining_seconds
        if remaining <= 0:
            self._expire_recurring(record.task_id)
            return
        try:
            handle = self._timers.schedule_once(
                f"scheduled-task-deadline:{self._group_id}/{record.task_id}",
                remaining,
                lambda: self._expire_recurring(record.task_id),
            )
        except BaseException as exc:
            self._state.mark_recurring_failed(
                record.task_id,
                exc,
                cancel_reason=f"scheduled task deadline registration failed: {record.task_id}",
            )
            raise
        if not self._state.bind_recurring_deadline(record, handle):
            handle.cancel()

    @staticmethod
    def _cancel_deadline_handle(handle: ScheduledTaskHandlePort | None) -> None:
        if handle is not None:
            handle.cancel()

    def _retire_group_deadline(self) -> None:
        """Disarm the one group-owned deadline after structural convergence."""
        self._cancel_deadline_handle(self._lifecycle.take_group_deadline())

    def _mark_running(self, task_id: str) -> None:
        self._state.mark_running(task_id)

    def _mark_succeeded(self, task_id: str) -> None:
        self._state.mark_succeeded(task_id)

    def _mark_cancelled(self, task_id: str, failure: BaseException | None = None) -> None:
        self._state.mark_cancelled(task_id, failure)

    def _mark_failed(self, task_id: str, failure: BaseException) -> None:
        self._state.mark_failed(task_id, failure)

    def _expire_task(self, task_id: str) -> TaskDeadlineExceeded:
        return self._state.expire_task(task_id)

    def _expire_recurring(self, task_id: str) -> None:
        self._state.expire_recurring(task_id)

    def _sync_terminal_from_raw(self, task_id: str) -> None:
        self._state.sync_terminal_from_raw(task_id)

    def _task_state(self, task_id: str) -> TaskState:
        return self._state.task_state(task_id)

    def _task_failure(self, task_id: str) -> BaseException | None:
        return self._state.task_failure(task_id)

    def _cancel_task(self, task_id: str, *, reason: str = "task cancelled") -> bool:
        return self._state.cancel_task(task_id, reason=reason)

    @staticmethod
    def _bounded_wait_timeout(deadline: Deadline | None, timeout: float | None) -> float | None:
        if timeout is not None and timeout < 0:
            raise ValueError("wait timeout cannot be negative")
        if deadline is None:
            return timeout
        remaining = deadline.remaining_seconds
        if timeout is None:
            return remaining
        return min(timeout, remaining)

    def _cancel_recurring(self, task_id: str) -> None:
        self._state.cancel_recurring(task_id)

    def _recurring_failure(self, task_id: str) -> BaseException | None:
        return self._state.recurring_failure(task_id)

    def cancel(self, reason: str) -> None:
        self._cancellation.cancel(reason)
        self._cancel_deadline_handle(self._lifecycle.take_group_deadline())
        self._state.cancel_all(reason=reason)

    def wait(self, *, timeout: float | None = None) -> None:
        """Join every physically submitted child before surfacing logical failures."""
        if timeout is not None and timeout < 0:
            raise ValueError("wait timeout cannot be negative")
        end = None if timeout is None else time.monotonic() + timeout
        records = self._state.task_records()
        recurring = self._state.recurring_records()
        errors: list[BaseException] = []
        for record in recurring:
            if record.timer_handle is None:
                continue
            try:
                _OwnedScheduledHandle(self, record, record.timer_handle).assert_healthy()
            except BaseException as exc:
                errors.append(exc)
        for record in records:
            raw = record.raw_handle
            if raw is None:
                state, failure, failure_scope = self._state.task_outcome(record.task_id)
                if (
                    failure is not None
                    and state is TaskState.FAILED
                    and failure_scope is TaskFailureScope.GROUP
                ):
                    errors.append(failure)
                continue
            remaining = None if end is None else max(0.0, end - time.monotonic())
            observed_failure: BaseException | None = None
            try:
                raw.result(timeout=remaining)
            except TimeoutError as exc:
                errors.append(exc)
                continue
            except BaseException as exc:
                observed_failure = exc
            state, failure, failure_scope = self._state.task_outcome(record.task_id)
            if state is TaskState.FAILED and failure_scope is TaskFailureScope.GROUP:
                if failure is not None:
                    errors.append(failure)
                elif observed_failure is not None:
                    errors.append(observed_failure)
                else:
                    errors.append(RuntimeError(f"failed task has no failure evidence: {record.task_id}"))
        for record in recurring:
            state, failure, current = self._state.recurring_outcome(record.task_id)
            if current is not None and not current.done():
                remaining = None if end is None else max(0.0, end - time.monotonic())
                observed_failure: BaseException | None = None
                try:
                    current.result(timeout=remaining)
                except TimeoutError as exc:
                    errors.append(exc)
                except BaseException as exc:
                    observed_failure = exc
            else:
                observed_failure = None
            state, failure, _current = self._state.recurring_outcome(record.task_id)
            if state is TaskState.FAILED:
                if failure is not None:
                    errors.append(failure)
                elif observed_failure is not None:
                    errors.append(observed_failure)
                else:
                    errors.append(RuntimeError(f"failed recurring task has no failure evidence: {record.task_id}"))
        if errors:
            raise ExceptionGroup(f"task group failed: {self._group_id}", errors)

    def assert_healthy(self) -> None:
        failures = self._state.failures()
        if failures:
            raise ExceptionGroup(f"task group unhealthy: {self._group_id}", list(failures))


    def snapshot(self) -> TaskGroupTopologySnapshot:
        lifecycle = self._lifecycle.snapshot()
        return TaskGroupTopologySnapshot(
            group_id=self._group_id,
            failure_policy=self._failure_policy,
            deadline_monotonic=None if self._deadline is None else self._deadline.monotonic_deadline,
            cancelled=self._cancellation.cancelled,
            closing=lifecycle.closing,
            closed=lifecycle.closed,
            converged=lifecycle.converged,
            cancellation_reason=self._cancellation.reason,
            tasks=self._state.topology(),
        )

    def _all_execution_done(self) -> bool:
        return self._state.all_execution_done()

    def _wait_for_submissions(self, deadline: Deadline) -> None:
        self._lifecycle.wait_for_submissions(deadline=deadline, group_id=self._group_id)

    def close(
        self,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        effective = deadline or Deadline.after(self._shutdown_timeout_seconds)
        disposition, existing_failure = self._lifecycle.begin_close()
        if disposition is _CloseDisposition.COMPLETE:
            if existing_failure is not None:
                raise existing_failure
            return
        if disposition is _CloseDisposition.WAIT:
            failure = self._lifecycle.wait_for_existing_close(
                deadline=effective,
                group_id=self._group_id,
            )
            if failure is not None:
                raise failure
            return

        self._submission_cancellation.cancel("task group closing submissions")
        errors: list[BaseException] = []
        submissions_quiesced = False
        on_close_succeeded = self._on_close is None
        try:
            if cancel_pending:
                self.cancel("task group closing")
            try:
                self._wait_for_submissions(effective)
            except BaseException as exc:
                errors.append(exc)
            else:
                submissions_quiesced = True

            self._state.cancel_all_recurring()
            try:
                self.wait(timeout=effective.remaining_seconds)
            except BaseException as exc:
                errors.append(exc)
            if self._on_close is not None:
                try:
                    self._on_close(self._group_id, effective)
                except BaseException as exc:
                    errors.append(exc)
                else:
                    on_close_succeeded = True
        finally:
            failure: BaseException | None = None
            if errors:
                failure = errors[0] if len(errors) == 1 else ExceptionGroup(
                    f"task group close failed: {self._group_id}",
                    errors,
                )
            converged = submissions_quiesced and self._all_execution_done() and on_close_succeeded
            if converged:
                self._retire_group_deadline()
            self._lifecycle.complete_close(failure=failure, converged=converged)

        if failure is not None:
            raise failure

    def __enter__(self) -> "StructuredTaskGroup":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc is not None:
            self.cancel(f"task group scope failed: {type(exc).__name__}")
        self.close(cancel_pending=exc is not None)
        return False


__all__ = ["StructuredTaskGroup"]
