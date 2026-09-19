from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ConcurrencyTopologySnapshot,
    Deadline,
    ExecutionPermitPort,
    HeartbeatSchedulerPort,
    SerialLaneTopologySnapshot,
    TaskFailurePolicy,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import (
    CpuWorkerPoolProviderPort,
    ExecutorProviderPort,
    SerialExecutionLaneFactoryProviderPort,
    SerialExecutionLaneProviderPort,
    TimerSchedulerProviderPort,
)
from .execution import UnifiedExecutionAuthority
from .heartbeat import UnifiedHeartbeatScheduler
from .task_group import StructuredTaskGroup


@dataclass(slots=True)
class _OwnedLane:
    owner_group_id: str
    capacity: int
    lane: SerialExecutionLaneProviderPort
    closed: bool = False


@dataclass(slots=True)
class StructuredConcurrencyRuntime:
    """Process-owned structured-concurrency and topology authority."""

    budget: ConcurrencyBudget
    _blocking_io: ExecutorProviderPort
    _async_io: ExecutorProviderPort
    _cpu: CpuWorkerPoolProviderPort
    _timers: TimerSchedulerProviderPort
    _serial_lane_factory: SerialExecutionLaneFactoryProviderPort
    _groups: dict[str, StructuredTaskGroup] = field(default_factory=dict)
    _serial_lanes: dict[str, _OwnedLane] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _closing: bool = False
    _closed: bool = False
    _converged: bool = False
    _close_complete: Event = field(default_factory=Event)
    _close_failure: BaseException | None = None
    _permits: ExecutionPermitPort | None = None
    _heartbeat_scheduler: UnifiedHeartbeatScheduler = field(init=False)
    _execution: UnifiedExecutionAuthority = field(init=False)

    def __post_init__(self) -> None:
        self._execution = UnifiedExecutionAuthority(
            blocking_io=self._blocking_io,
            async_io=self._async_io,
            cpu=self._cpu,
            lane_resolver=self._resolve_serial_lane,
            permits=self._permits,
        )
        self._heartbeat_scheduler = UnifiedHeartbeatScheduler(self._resolve_group_for_heartbeat)

    @property
    def heartbeats(self) -> HeartbeatSchedulerPort:
        return self._heartbeat_scheduler

    def _resolve_group_for_heartbeat(self, group_id: str) -> StructuredTaskGroup:
        group_id = str(group_id).strip()
        if not group_id:
            raise ValueError("heartbeat owner group id required")
        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("concurrency runtime is closed")
            group = self._groups.get(group_id)
            if group is None:
                raise KeyError(f"heartbeat owner task group not found: {group_id}")
            return group

    def open_task_group(
        self,
        group_id: str,
        *,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        group_id = str(group_id).strip()
        if not group_id:
            raise ValueError("task group id required")
        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("concurrency runtime is closed")
            if group_id in self._groups:
                raise ValueError(f"task group id already owned: {group_id}")
            group = StructuredTaskGroup(
                group_id=group_id,
                execution=self._execution,
                timers=self._timers,
                default_queue_capacity=self.budget.default_queue_capacity,
                deadline=deadline,
                failure_policy=failure_policy,
                shutdown_timeout_seconds=self.budget.shutdown_timeout_seconds,
                on_close=self._close_group_lanes,
            )
            self._groups[group_id] = group
            return group

    def _resolve_serial_lane(
        self,
        owner_group_id: str,
        lane_id: str,
        capacity: int | None,
    ) -> SerialExecutionLaneProviderPort:
        lane_id = str(lane_id).strip()
        if not lane_id:
            raise ValueError("serial lane id required")
        resolved_capacity = self.budget.default_queue_capacity if capacity is None else int(capacity)
        if resolved_capacity <= 0:
            raise ValueError("serial lane capacity must be positive")
        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("concurrency runtime is closed")
            owned = self._serial_lanes.get(lane_id)
            if owned is not None:
                if owned.owner_group_id != owner_group_id:
                    raise ValueError(
                        f"serial lane already owned by another task group: {lane_id}: "
                        f"{owned.owner_group_id}"
                    )
                if owned.closed:
                    raise RuntimeError(f"serial lane is closed: {lane_id}")
                if owned.capacity != resolved_capacity:
                    raise ValueError(
                        f"serial lane capacity mismatch: {lane_id}: "
                        f"owned={owned.capacity} requested={resolved_capacity}"
                    )
                return owned.lane
            lane = self._serial_lane_factory.create(lane_id, capacity=resolved_capacity)
            self._serial_lanes[lane_id] = _OwnedLane(owner_group_id, resolved_capacity, lane)
            return lane

    def _close_group_lanes(self, group_id: str, deadline: Deadline) -> None:
        with self._lock:
            lanes = tuple(
                owned
                for owned in self._serial_lanes.values()
                if owned.owner_group_id == group_id and not owned.closed
            )
        errors: list[BaseException] = []
        for owned in lanes:
            try:
                owned.lane.close(cancel_pending=False, deadline=deadline)
            except BaseException as exc:
                errors.append(exc)
            else:
                with self._lock:
                    owned.closed = True
        if errors:
            raise ExceptionGroup(f"serial lane shutdown failed for group: {group_id}", errors)

    def release_task_group(self, group_id: str) -> None:
        resolved = str(group_id).strip()
        if not resolved:
            raise ValueError("task group id required")
        with self._lock:
            group = self._groups.get(resolved)
            if group is None:
                return
            snapshot = group.snapshot()
            if not snapshot.closed or not snapshot.converged:
                raise RuntimeError(
                    f"cannot release task group before physical convergence: {resolved}"
                )
            owned_lane_ids = tuple(
                lane_id for lane_id, owned in self._serial_lanes.items()
                if owned.owner_group_id == resolved
            )
            if any(not self._serial_lanes[lane_id].closed for lane_id in owned_lane_ids):
                raise RuntimeError(
                    f"cannot release task group with live serial lanes: {resolved}"
                )
            self._groups.pop(resolved, None)
            for lane_id in owned_lane_ids:
                self._serial_lanes.pop(lane_id, None)

    def topology_snapshot(self) -> ConcurrencyTopologySnapshot:
        with self._lock:
            groups = tuple(self._groups.values())
            lanes = tuple(
                owned.lane.topology_snapshot(
                    owner_group_id=owned.owner_group_id,
                    closed=owned.closed,
                )
                for owned in self._serial_lanes.values()
            )
            closing = self._closing
            closed = self._closed
            converged = self._converged
            failure = self._close_failure
        return ConcurrencyTopologySnapshot(
            closing=closing,
            closed=closed,
            converged=converged,
            shutdown_failure_type=None if failure is None else type(failure).__name__,
            groups=tuple(sorted((group.snapshot() for group in groups), key=lambda item: item.group_id)),
            serial_lanes=tuple(sorted(lanes, key=lambda item: item.lane_id)),
            heartbeats=self._heartbeat_scheduler.snapshot(),
        )

    @staticmethod
    def _contains_timeout(error: BaseException) -> bool:
        if isinstance(error, TimeoutError):
            return True
        if isinstance(error, BaseExceptionGroup):
            return any(StructuredConcurrencyRuntime._contains_timeout(item) for item in error.exceptions)
        return False

    def close(self, *, deadline: Deadline | None = None) -> None:
        effective = deadline or Deadline.after(self.budget.shutdown_timeout_seconds)
        with self._lock:
            if self._closed and self._converged:
                failure = self._close_failure
                if failure is not None:
                    raise failure
                return
            if self._closing:
                wait_for_existing_close = True
            else:
                # closed means sealed against new ownership; converged means every
                # owned execution/provider has actually joined.  A failed bounded
                # close remains sealed but is retryable so a later caller can prove
                # physical convergence once non-preemptive work has ended.
                self._closing = True
                self._close_failure = None
                self._close_complete.clear()
                groups = tuple(self._groups.values())
                lanes = tuple(self._serial_lanes.values())
                wait_for_existing_close = False

        if wait_for_existing_close:
            if not self._close_complete.wait(effective.remaining_seconds):
                raise TimeoutError("concurrency runtime close did not converge")
            with self._lock:
                failure = self._close_failure
            if failure is not None:
                raise failure
            return

        errors: list[BaseException] = []
        timed_out = False
        timer_joined = False
        providers_joined = False
        try:
            for group in reversed(groups):
                snapshot = group.snapshot()
                if snapshot.converged:
                    continue
                try:
                    group.close(cancel_pending=True, deadline=effective)
                except BaseException as exc:
                    errors.append(exc)
                    timed_out = timed_out or self._contains_timeout(exc)
            for owned in reversed(lanes):
                if owned.closed:
                    continue
                try:
                    owned.lane.close(cancel_pending=True, deadline=effective)
                    owned.closed = True
                except BaseException as exc:
                    errors.append(exc)
                    timed_out = timed_out or self._contains_timeout(exc)
            try:
                self._serial_lane_factory.close(cancel_pending=True, deadline=effective)
            except BaseException as exc:
                errors.append(exc)
                timed_out = timed_out or self._contains_timeout(exc)
            try:
                self._timers.close(deadline=effective)
            except BaseException as exc:
                errors.append(exc)
                timed_out = timed_out or self._contains_timeout(exc)
            else:
                timer_joined = True
            # If the structured join deadline was breached, do not replace the
            # explicit convergence error with an unbounded Executor.shutdown().
            provider_errors_before = len(errors)
            for provider in (self._blocking_io, self._async_io, self._cpu):
                try:
                    provider.close(wait=not timed_out, cancel_pending=True)
                except BaseException as exc:
                    errors.append(exc)
            providers_joined = not timed_out and len(errors) == provider_errors_before
        finally:
            failure: BaseException | None = None
            if errors:
                failure = ExceptionGroup("concurrency runtime shutdown failed", errors)
            group_converged = all(group.snapshot().converged for group in groups)
            lanes_converged = all(owned.closed for owned in lanes)
            # Logical child failures are reported independently through
            # ``shutdown_failure_type``. Convergence means only that every owned
            # execution lane/provider has physically joined. This definition is
            # invariant to whether callers observed a group's logical failure
            # before asking the runtime to close.
            converged = group_converged and lanes_converged and timer_joined and providers_joined
            with self._lock:
                self._close_failure = failure
                self._closed = True
                self._converged = converged
                self._closing = False
            self._close_complete.set()

        if failure is not None:
            raise failure


    def __enter__(self) -> "StructuredConcurrencyRuntime":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False
