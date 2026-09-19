from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind, ExecutionPermitRejected


class AdmissionMode(StrEnum):
    """Group-level behavior when hierarchical capacity is unavailable."""

    BLOCK = "block"
    REJECT = "reject"


class AdmissionRejected(ExecutionPermitRejected):
    """Raised when an admission request uses reject semantics and has no capacity."""


@dataclass(frozen=True, slots=True)
class AdmissionBudget:
    max_total_in_flight: int = 64
    max_in_flight_per_group: int | None = None
    max_in_flight_per_tenant: int | None = None
    max_in_flight_per_resource: int | None = None
    max_blocking_io_in_flight: int | None = None
    max_async_io_in_flight: int | None = None
    max_cpu_in_flight: int | None = None
    max_serial_in_flight: int | None = None

    def __post_init__(self) -> None:
        def require_limit(value: int | None, *, name: str, fallback: int | None = None) -> int:
            if value is None:
                if fallback is None:
                    raise TypeError(f"{name} must be an integer")
                return fallback
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            return value

        total = require_limit(self.max_total_in_flight, name="max_total_in_flight")
        group = require_limit(self.max_in_flight_per_group, name="max_in_flight_per_group", fallback=total)
        tenant = require_limit(self.max_in_flight_per_tenant, name="max_in_flight_per_tenant", fallback=total)
        resource = require_limit(self.max_in_flight_per_resource, name="max_in_flight_per_resource", fallback=total)
        blocking = require_limit(self.max_blocking_io_in_flight, name="max_blocking_io_in_flight", fallback=total)
        async_io = require_limit(self.max_async_io_in_flight, name="max_async_io_in_flight", fallback=total)
        cpu = require_limit(self.max_cpu_in_flight, name="max_cpu_in_flight", fallback=total)
        serial = require_limit(self.max_serial_in_flight, name="max_serial_in_flight", fallback=total)
        for name, value in (
            ("max_total_in_flight", total),
            ("max_in_flight_per_group", group),
            ("max_in_flight_per_tenant", tenant),
            ("max_in_flight_per_resource", resource),
            ("max_blocking_io_in_flight", blocking),
            ("max_async_io_in_flight", async_io),
            ("max_cpu_in_flight", cpu),
            ("max_serial_in_flight", serial),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name, value in (
            ("max_in_flight_per_group", group),
            ("max_in_flight_per_tenant", tenant),
            ("max_in_flight_per_resource", resource),
            ("max_blocking_io_in_flight", blocking),
            ("max_async_io_in_flight", async_io),
            ("max_cpu_in_flight", cpu),
            ("max_serial_in_flight", serial),
        ):
            if value > total:
                raise ValueError(f"{name} cannot exceed max_total_in_flight")
        object.__setattr__(self, "max_total_in_flight", total)
        object.__setattr__(self, "max_in_flight_per_group", group)
        object.__setattr__(self, "max_in_flight_per_tenant", tenant)
        object.__setattr__(self, "max_in_flight_per_resource", resource)
        object.__setattr__(self, "max_blocking_io_in_flight", blocking)
        object.__setattr__(self, "max_async_io_in_flight", async_io)
        object.__setattr__(self, "max_cpu_in_flight", cpu)
        object.__setattr__(self, "max_serial_in_flight", serial)

    def lane_limit(self, lane_kind: ExecutionLaneKind) -> int:
        if lane_kind is ExecutionLaneKind.BLOCKING_IO:
            return self.max_blocking_io_in_flight
        if lane_kind is ExecutionLaneKind.ASYNC_IO:
            return self.max_async_io_in_flight
        if lane_kind is ExecutionLaneKind.CPU:
            return self.max_cpu_in_flight
        if lane_kind is ExecutionLaneKind.SERIAL:
            return self.max_serial_in_flight
        raise ValueError(f"timer is not an admission lane: {lane_kind}")


@dataclass(frozen=True, slots=True)
class AdmissionIdentity:
    tenant_id: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("tenant_id", "resource_id"):
            value = getattr(self, field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{field} must be text or null")
            resolved = value.strip()
            if not resolved:
                raise ValueError(f"{field} cannot be blank")
            object.__setattr__(self, field, resolved)


@dataclass(frozen=True, slots=True)
class AdmissionIntent:
    priority: ExecutionPriority = ExecutionPriority.NORMAL
    mode: AdmissionMode = AdmissionMode.BLOCK

    def __post_init__(self) -> None:
        if not isinstance(self.priority, ExecutionPriority):
            raise TypeError("admission priority must be ExecutionPriority")
        if not isinstance(self.mode, AdmissionMode):
            raise TypeError("admission mode must be AdmissionMode")


@dataclass(frozen=True, slots=True)
class GroupAdmissionSnapshot:
    group_id: str
    tenant_id: str | None
    resource_id: str | None
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class TenantAdmissionSnapshot:
    tenant_id: str
    max_in_flight: int
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class ResourceAdmissionSnapshot:
    tenant_id: str | None
    resource_id: str
    max_in_flight: int
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class LaneAdmissionSnapshot:
    lane_kind: ExecutionLaneKind
    max_in_flight: int
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class AdmissionTopologySnapshot:
    max_total_in_flight: int
    max_in_flight_per_group: int
    max_in_flight_per_tenant: int
    max_in_flight_per_resource: int
    in_flight: int
    waiting: int
    closed: bool
    admitted_total: int
    rejected_total: int
    cancelled_total: int
    timed_out_total: int
    queued_total: int
    cumulative_queue_wait_seconds: float
    max_queue_wait_seconds: float
    oldest_wait_seconds: float
    groups: tuple[GroupAdmissionSnapshot, ...]
    tenants: tuple[TenantAdmissionSnapshot, ...]
    resources: tuple[ResourceAdmissionSnapshot, ...]
    lanes: tuple[LaneAdmissionSnapshot, ...]
