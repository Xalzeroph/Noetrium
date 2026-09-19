from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
import time


class ExecutionLaneKind(StrEnum):
    SERIAL = "serial"
    BLOCKING_IO = "blocking-io"
    ASYNC_IO = "async-io"
    CPU = "cpu"
    TIMER = "timer"


class SerialMailboxPolicy(StrEnum):
    """Mechanical overflow behavior for one bounded SERIAL mailbox only."""

    BLOCK = "block"
    REJECT = "reject"
    COALESCE = "coalesce"


class TaskFailurePolicy(StrEnum):
    FAIL_FAST = "fail-fast"
    COLLECT_ALL = "collect-all"


class TaskFailureScope(StrEnum):
    GROUP = "group"
    CALLER = "caller"


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCancelled(RuntimeError):
    """Raised by a cooperative task after its owning scope is cancelled."""


class TaskDeadlineExceeded(TimeoutError):
    """Raised when a task reaches its monotonic execution deadline."""


class ExecutionPermitRejected(RuntimeError):
    """Neutral pre-execution rejection from an injected permit authority."""


class SerialMailboxRejected(RuntimeError):
    """Raised when a SERIAL mailbox uses REJECT and has no local capacity."""


@dataclass(frozen=True, slots=True)
class ConcurrencyBudget:
    """Mechanical provider capacities owned by platform/concurrency only."""

    max_blocking_io_workers: int = 8
    max_serial_workers: int = 8
    max_cpu_workers: int = max(1, min(8, os.cpu_count() or 1))
    max_blocking_io_in_flight: int | None = None
    max_async_io_in_flight: int = 64
    max_cpu_in_flight: int | None = None
    default_queue_capacity: int = 1024
    shutdown_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        blocking = self.max_blocking_io_workers if self.max_blocking_io_in_flight is None else int(self.max_blocking_io_in_flight)
        cpu = self.max_cpu_workers if self.max_cpu_in_flight is None else int(self.max_cpu_in_flight)
        object.__setattr__(self, "max_blocking_io_in_flight", blocking)
        object.__setattr__(self, "max_cpu_in_flight", cpu)
        values = (
            self.max_blocking_io_workers,
            self.max_serial_workers,
            self.max_cpu_workers,
            blocking,
            self.max_async_io_in_flight,
            cpu,
            self.default_queue_capacity,
            self.shutdown_timeout_seconds,
        )
        if min(values) <= 0:
            raise ValueError("concurrency budget values must be positive")
        if blocking < self.max_blocking_io_workers:
            raise ValueError("blocking I/O in-flight capacity cannot be below worker capacity")
        if cpu < self.max_cpu_workers:
            raise ValueError("CPU in-flight capacity cannot be below worker capacity")


@dataclass(frozen=True, slots=True)
class Deadline:
    monotonic_deadline: float

    @classmethod
    def after(cls, timeout_seconds: float) -> "Deadline":
        if timeout_seconds <= 0:
            raise ValueError("deadline timeout must be positive")
        return cls(time.monotonic() + timeout_seconds)

    def child(self, timeout_seconds: float) -> "Deadline":
        """Create a child deadline that can only tighten this deadline."""

        if timeout_seconds <= 0:
            raise ValueError("child deadline timeout must be positive")
        return Deadline(min(self.monotonic_deadline, time.monotonic() + timeout_seconds))

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.monotonic_deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0.0


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    """One owner-visible execution mechanism request.

    ``lane_kind`` selects the execution domain while ``lane_id``/``capacity`` are
    meaningful only for SERIAL work.  Business systems use this single contract
    instead of importing thread/process/serial executor-specific seams.
    """

    task_id: str
    lane_kind: ExecutionLaneKind
    lane_id: str | None = None
    capacity: int | None = None
    mailbox_policy: SerialMailboxPolicy = SerialMailboxPolicy.BLOCK
    coalesce_key: str | None = None
    failure_scope: TaskFailureScope = TaskFailureScope.GROUP

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("execution task_id required")
        if self.lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer is a scheduling authority, not an execution lane")
        if self.lane_kind is ExecutionLaneKind.SERIAL:
            if self.lane_id is None or not self.lane_id.strip():
                raise ValueError("serial execution requires lane_id")
            if self.capacity is not None and self.capacity <= 0:
                raise ValueError("serial execution capacity must be positive")
        elif self.lane_id is not None or self.capacity is not None:
            raise ValueError("lane_id/capacity are valid only for serial execution")
        if self.mailbox_policy is SerialMailboxPolicy.COALESCE:
            if self.lane_kind is not ExecutionLaneKind.SERIAL:
                raise ValueError("coalescing backpressure is valid only for serial execution")
            if self.coalesce_key is None or not self.coalesce_key.strip():
                raise ValueError("coalescing serial execution requires coalesce_key")
        elif self.coalesce_key is not None:
            raise ValueError("coalesce_key requires COALESCE serial mailbox policy")
        if self.lane_kind is not ExecutionLaneKind.SERIAL and self.mailbox_policy is not SerialMailboxPolicy.BLOCK:
            raise ValueError("mailbox_policy is valid only for serial execution")


@dataclass(frozen=True, slots=True)
class HeartbeatSpec:
    """Registration for the one process-wide heartbeat scheduler authority."""

    heartbeat_id: str
    lane_id: str
    interval_seconds: float
    initial_delay_seconds: float | None = None
    lane_capacity: int | None = None

    def __post_init__(self) -> None:
        if not self.heartbeat_id.strip():
            raise ValueError("heartbeat_id required")
        if not self.lane_id.strip():
            raise ValueError("heartbeat lane_id required")
        if self.interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        if self.initial_delay_seconds is not None and self.initial_delay_seconds < 0:
            raise ValueError("heartbeat initial delay cannot be negative")
        if self.lane_capacity is not None and self.lane_capacity <= 0:
            raise ValueError("heartbeat lane capacity must be positive")

    @property
    def resolved_initial_delay_seconds(self) -> float:
        return self.interval_seconds if self.initial_delay_seconds is None else self.initial_delay_seconds


@dataclass(frozen=True, slots=True)
class ScheduledTaskSpec:
    task_id: str
    interval_seconds: float
    initial_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("scheduled task_id required")
        if self.interval_seconds <= 0:
            raise ValueError("scheduled task interval must be positive")
        if self.initial_delay_seconds < 0:
            raise ValueError("scheduled task initial delay cannot be negative")


@dataclass(frozen=True, slots=True)
class TaskTopologySnapshot:
    group_id: str
    task_id: str
    lane_kind: ExecutionLaneKind
    lane_id: str | None
    state: TaskState
    execution_done: bool
    deadline_monotonic: float | None
    failure_type: str | None = None
    failure_scope: TaskFailureScope = TaskFailureScope.GROUP


@dataclass(frozen=True, slots=True)
class TaskGroupTopologySnapshot:
    group_id: str
    failure_policy: TaskFailurePolicy
    deadline_monotonic: float | None
    cancelled: bool
    closing: bool
    closed: bool
    converged: bool
    cancellation_reason: str | None
    tasks: tuple[TaskTopologySnapshot, ...]


@dataclass(frozen=True, slots=True)
class SerialLaneTopologySnapshot:
    lane_id: str
    owner_group_id: str
    capacity: int
    closed: bool
    queued_work_items: int
    running: bool
    scheduled: bool
    coalesced_keys: int
    logical_outstanding: int
    accepted_work_items_total: int
    completed_work_items_total: int
    failed_work_items_total: int
    coalesced_submissions_total: int
    mailbox_full_events_total: int
    max_queue_depth: int


@dataclass(frozen=True, slots=True)
class HeartbeatTopologySnapshot:
    heartbeat_id: str
    owner_group_id: str
    lane_id: str
    interval_seconds: float
    active: bool
    failure_type: str | None = None


@dataclass(frozen=True, slots=True)
class ConcurrencyTopologySnapshot:
    closing: bool
    closed: bool
    converged: bool
    shutdown_failure_type: str | None
    groups: tuple[TaskGroupTopologySnapshot, ...]
    serial_lanes: tuple[SerialLaneTopologySnapshot, ...]
    heartbeats: tuple[HeartbeatTopologySnapshot, ...]
