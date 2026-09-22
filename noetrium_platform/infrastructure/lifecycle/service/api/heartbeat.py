from __future__ import annotations

from dataclasses import dataclass
import math
import time


@dataclass(frozen=True, slots=True)
class ServiceHeartbeat:
    deployment_id: str
    stack_digest: str
    pid: int
    process_start_marker: str
    argv_digest: str
    ready: bool
    qualification_digest: str | None
    timestamp: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.timestamp, bool)
            or not isinstance(self.timestamp, (int, float))
            or not math.isfinite(float(self.timestamp))
            or self.timestamp < 0
        ):
            raise ValueError("service heartbeat timestamp must be finite and non-negative")

    def age(self, now: float | None = None) -> float:
        current = time.time() if now is None else now
        if (
            isinstance(current, bool)
            or not isinstance(current, (int, float))
            or not math.isfinite(float(current))
            or current < 0
        ):
            raise ValueError("service heartbeat age reference must be finite and non-negative")
        return max(0.0, float(current) - float(self.timestamp))
