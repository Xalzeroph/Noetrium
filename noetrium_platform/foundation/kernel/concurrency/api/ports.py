from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar

from .contracts import (
    ConcurrencyTopologySnapshot,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    HeartbeatSpec,
    HeartbeatTopologySnapshot,
    ScheduledTaskSpec,
    TaskFailurePolicy,
    TaskGroupTopologySnapshot,
    TaskState,
    SerialLaneTopologySnapshot,
)

T = TypeVar("T")
R = TypeVar("R")


class CancellationTokenPort(Protocol):
    @property
    def cancelled(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    def wait(self, timeout: float | None = None) -> bool: ...
    def checkpoint(self) -> None: ...


class ExecutionPermitLeasePort(Protocol):
    def release(self) -> None: ...


class ExecutionPermitPort(Protocol):
    """Neutral permit gate consumed by the concurrency mechanism.

    Policy systems may implement this port, but platform/concurrency does not
    know why a permit is granted or rejected.
    """

    def acquire(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> ExecutionPermitLeasePort: ...


class TaskContextPort(CancellationTokenPort, Protocol):
    @property
    def group_id(self) -> str: ...
    @property
    def task_id(self) -> str: ...
    @property
    def lane_kind(self) -> ExecutionLaneKind: ...
    @property
    def deadline(self) -> Deadline | None: ...
    @property
    def remaining_seconds(self) -> float | None: ...


class TaskHandlePort(Protocol[T]):
    @property
    def task_id(self) -> str: ...
    @property
    def lane_kind(self) -> ExecutionLaneKind: ...
    @property
    def state(self) -> TaskState: ...
    def done(self) -> bool: ...
    def cancel(self) -> bool: ...
    def result(self, timeout: float | None = None) -> T: ...


class ScheduledTaskHandlePort(Protocol):
    @property
    def task_id(self) -> str: ...
    def cancel(self) -> None: ...
    def assert_healthy(self) -> None: ...


class ExecutorPort(Protocol):
    def submit(
        self,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]: ...


class SerialActorPort(Protocol):
    @property
    def actor_id(self) -> str: ...

    def submit(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]: ...

    def call(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> T: ...


class TaskGroupPort(ExecutorPort, Protocol):
    @property
    def group_id(self) -> str: ...
    @property
    def cancellation(self) -> CancellationTokenPort: ...
    def open_serial_actor(
        self,
        actor_id: str,
        *,
        lane_id: str | None = None,
        capacity: int | None = None,
    ) -> SerialActorPort: ...

    def cancel(self, reason: str) -> None: ...
    def wait(self, *, timeout: float | None = None) -> None: ...
    def assert_healthy(self) -> None: ...
    def snapshot(self) -> TaskGroupTopologySnapshot: ...
    def close(self, *, cancel_pending: bool = False, deadline: Deadline | None = None) -> None: ...


class HeartbeatSchedulerPort(Protocol):
    def register(
        self,
        owner_group_id: str,
        spec: HeartbeatSpec,
        fn: Callable[..., Any],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> ScheduledTaskHandlePort: ...
    def snapshot(self) -> tuple[HeartbeatTopologySnapshot, ...]: ...


class StructuredConcurrencyRuntimePort(Protocol):
    @property
    def heartbeats(self) -> HeartbeatSchedulerPort: ...
    def open_task_group(
        self,
        group_id: str,
        *,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort: ...
    def release_task_group(self, group_id: str) -> None: ...
    def topology_snapshot(self) -> ConcurrencyTopologySnapshot: ...
    def assert_healthy(self) -> None: ...
    def close(self, *, deadline: Deadline | None = None) -> None: ...


# Provider-facing ports. They are intentionally not re-exported from
# platform.concurrency.api: business/runtime systems must enter through a task
# group so ownership, cancellation and deadline semantics cannot be bypassed.
class ExecutionAuthorityProviderPort(Protocol):
    def ensure_serial_lane(
        self,
        owner_group_id: str,
        lane_id: str,
        capacity: int | None,
    ) -> "SerialExecutionLaneProviderPort": ...

    def submit(
        self,
        owner_group_id: str,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any: ...


class ExecutorProviderPort(Protocol):
    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any: ...
    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None: ...


class CpuWorkerPoolProviderPort(ExecutorProviderPort, Protocol):
    def map(self, fn: Callable[[T], R], values: Iterable[T], *, chunksize: int = 1) -> tuple[R, ...]: ...


class SerialExecutionLaneProviderPort(Protocol):
    @property
    def lane_id(self) -> str: ...
    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any: ...
    def try_submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any | None: ...
    def try_coalesce(
        self,
        coalesce_key: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any | None: ...
    def try_submit_coalesced(
        self,
        coalesce_key: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> tuple[Any, bool, Any | None] | None: ...
    def topology_snapshot(self, *, owner_group_id: str, closed: bool) -> SerialLaneTopologySnapshot: ...
    def close(self, *, cancel_pending: bool = False, deadline: Deadline | None = None) -> None: ...


class SerialExecutionLaneFactoryProviderPort(Protocol):
    def create(self, lane_id: str, *, capacity: int) -> SerialExecutionLaneProviderPort: ...
    def close(
        self,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None: ...


class TimerSchedulerProviderPort(Protocol):
    def schedule_once(
        self,
        task_id: str,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandlePort: ...
    def schedule_fixed_delay(self, spec: ScheduledTaskSpec, callback: Callable[[], None]) -> ScheduledTaskHandlePort: ...
    def close(self, *, deadline: Deadline | None = None) -> None: ...
