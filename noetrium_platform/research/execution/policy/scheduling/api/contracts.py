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
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "enqueued_monotonic", enqueued)
