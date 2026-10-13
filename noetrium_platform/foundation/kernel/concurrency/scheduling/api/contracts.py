from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class ExecutionPriority(StrEnum):
    """Generic scheduling intent; ranking semantics belong to scheduling runtime."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SchedulingCandidate:
    """State-free description of one feasible scheduling choice.

    Capacity/resource authorities decide feasibility.  This value contains only
    ordering facts so every execution domain can share one scheduling law.
    """

    ticket: int
    group_id: str
    priority: ExecutionPriority
    enqueued_monotonic: float
    tenant_id: str | None = None
    resource_id: str | None = None
    flow_id: str | None = None
    continuity_rank: int = 1
    waiting_permits: int = 1
    observed_service_rate_per_second: float | None = None
    deadline_monotonic: float | None = None
    estimated_service_seconds: float | None = None
    speculation_rank: int = 0
    critical_path_tail_work: float = 0.0
    expected_waste_cost: float = 0.0
    estimated_service_cost: float = 0.0
    deterministic_tiebreak: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.ticket, bool) or not isinstance(self.ticket, int) or self.ticket < 0:
            raise TypeError("scheduling ticket must be a non-negative integer")
        if not isinstance(self.group_id, str):
            raise TypeError("scheduling group_id must be text")
        group_id = self.group_id.strip()
        if not group_id:
            raise ValueError("scheduling group_id required")
        if not isinstance(self.priority, ExecutionPriority):
            raise TypeError("scheduling priority must be ExecutionPriority")
        if isinstance(self.enqueued_monotonic, bool) or not isinstance(
            self.enqueued_monotonic, (int, float)
        ):
            raise TypeError("scheduling enqueue time must be numeric")
        enqueued = float(self.enqueued_monotonic)
        if not math.isfinite(enqueued) or enqueued < 0:
            raise ValueError("scheduling enqueue time must be finite and non-negative")

        for field_name in ("tenant_id", "resource_id", "flow_id"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"scheduling {field_name} must be text or null")
            value = value.strip()
            if not value:
                raise ValueError(f"scheduling {field_name} cannot be blank")
            object.__setattr__(self, field_name, value)

        if type(self.continuity_rank) is not int or self.continuity_rank < 0:
            raise ValueError("scheduling continuity_rank must be a non-negative integer")
        if type(self.waiting_permits) is not int or self.waiting_permits <= 0:
            raise ValueError("scheduling waiting_permits must be a positive integer")

        rate = self.observed_service_rate_per_second
        if rate is not None:
            if (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(float(rate))
                or float(rate) <= 0.0
            ):
                raise ValueError(
                    "scheduling observed service rate must be finite and positive"
                )
            object.__setattr__(
                self,
                "observed_service_rate_per_second",
                float(rate),
            )

        deadline = self.deadline_monotonic
        if deadline is not None:
            if (
                isinstance(deadline, bool)
                or not isinstance(deadline, (int, float))
                or not math.isfinite(float(deadline))
                or float(deadline) < 0.0
            ):
                raise ValueError(
                    "scheduling deadline_monotonic must be finite and non-negative"
                )
            object.__setattr__(self, "deadline_monotonic", float(deadline))

        service_seconds = self.estimated_service_seconds
        if service_seconds is not None:
            if isinstance(service_seconds, bool) or not isinstance(
                service_seconds, (int, float)
            ):
                raise TypeError(
                    "scheduling estimated_service_seconds must be numeric or null"
                )
            service_seconds = float(service_seconds)
            if not math.isfinite(service_seconds) or service_seconds < 0.0:
                raise ValueError(
                    "scheduling estimated_service_seconds must be finite and non-negative"
                )
            object.__setattr__(
                self,
                "estimated_service_seconds",
                service_seconds,
            )

        if type(self.speculation_rank) is not int or self.speculation_rank < 0:
            raise ValueError(
                "scheduling speculation_rank must be a non-negative integer"
            )
        work = self.critical_path_tail_work
        if (
            isinstance(work, bool)
            or not isinstance(work, (int, float))
            or not math.isfinite(float(work))
            or float(work) < 0.0
        ):
            raise ValueError(
                "scheduling critical_path_tail_work must be finite and non-negative"
            )
        object.__setattr__(self, "critical_path_tail_work", float(work))
        for field_name in ("expected_waste_cost", "estimated_service_cost"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise ValueError(
                    f"scheduling {field_name} must be finite and non-negative"
                )
            object.__setattr__(self, field_name, float(value))
        if (
            type(self.deterministic_tiebreak) is not int
            or self.deterministic_tiebreak < 0
        ):
            raise ValueError(
                "scheduling deterministic_tiebreak must be a non-negative integer"
            )
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "enqueued_monotonic", enqueued)
