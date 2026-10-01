from __future__ import annotations

from dataclasses import dataclass
import math
from enum import StrEnum


class ExecutionPriority(StrEnum):
    """Generic scheduling intent; ranking semantics belong to scheduling runtime."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SchedulingCandidate:
    ticket: int
    group_id: str
    priority: ExecutionPriority
    enqueued_monotonic: float
    tenant_id: str | None = None
    group_in_flight: int = 0
    tenant_in_flight: int = 0

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
        if isinstance(self.enqueued_monotonic, bool) or not isinstance(self.enqueued_monotonic, (int, float)):
            raise TypeError("scheduling enqueue time must be numeric")
        enqueued = float(self.enqueued_monotonic)
        if not math.isfinite(enqueued) or enqueued < 0:
            raise ValueError("scheduling enqueue time must be finite and non-negative")
        for field_name in ("group_in_flight", "tenant_in_flight"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"scheduling {field_name} must be a non-negative integer"
                )
        tenant_id = self.tenant_id
        if tenant_id is not None:
            if not isinstance(tenant_id, str):
                raise TypeError("scheduling tenant_id must be text or null")
            tenant_id = tenant_id.strip()
            if not tenant_id:
                raise ValueError("scheduling tenant_id cannot be blank")
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "enqueued_monotonic", enqueued)
        object.__setattr__(self, "tenant_id", tenant_id)
