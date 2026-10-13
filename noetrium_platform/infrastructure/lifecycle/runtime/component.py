from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import heapq
import math
from pathlib import Path
import time

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_bytes,
    strict_json_loads,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)
from noetrium_platform.infrastructure.lifecycle.api.component import (
    LifecyclePhase,
)



class HealthClassification(StrEnum):
    READY = "ready"
    STARTING = "starting"
    STALLED = "stalled"
    FAILED = "failed"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResourceHealth:
    rss_bytes: int | None = None
    cpu_percent: float | None = None
    fd_count: int | None = None
    thread_count: int | None = None
    gpu_memory_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ComponentHealthRecord:
    component_id: str
    phase: LifecyclePhase
    generation: str
    pid: int | None
    process_start_identity: str | None
    heartbeat_interval_s: float | None
    last_heartbeat_at: float | None
    last_progress_at: float | None
    last_failure_id: str | None = None
    resource: ResourceHealth = ResourceHealth()
    updated_at: float = 0.0


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    component_id: str
    classification: str
    phase: LifecyclePhase
    heartbeat_age_s: float | None
    progress_age_s: float | None
    last_failure_id: str | None
    reason: str


class ComponentHealthStore:
    """Operational health projection owned by one infrastructure supervisor."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, record: ComponentHealthRecord) -> None:
        if not isinstance(record, ComponentHealthRecord):
            raise TypeError("health store requires ComponentHealthRecord")
        atomic_replace_bytes(self.path, canonical_bytes(record, indent=2))

    def read(self) -> ComponentHealthRecord:
        data = strict_json_loads(self.path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError("component health document must be an object")
        data["phase"] = LifecyclePhase(data["phase"])
        resource = data.get("resource", {})
        if not isinstance(resource, dict):
            raise ValueError("component health resource must be an object")
        data["resource"] = ResourceHealth(**resource)
        return ComponentHealthRecord(**data)


class HealthMonitor:
    def __init__(
        self,
        *,
        heartbeat_grace_multiplier: float = 3.0,
        progress_stall_s: float | None = None,
    ) -> None:
        if (
            not math.isfinite(float(heartbeat_grace_multiplier))
            or heartbeat_grace_multiplier <= 1
        ):
            raise ValueError(
                "heartbeat grace multiplier must be finite and exceed 1"
            )
        if progress_stall_s is not None and (
            not math.isfinite(float(progress_stall_s))
            or progress_stall_s <= 0
        ):
            raise ValueError("progress_stall_s must be finite and positive")
        self.heartbeat_grace_multiplier = float(
            heartbeat_grace_multiplier
        )
        self.progress_stall_s = (
            None if progress_stall_s is None else float(progress_stall_s)
        )

    def assess(
        self,
        record: ComponentHealthRecord,
        *,
        now: float | None = None,
    ) -> HealthAssessment:
        if not isinstance(record, ComponentHealthRecord):
            raise TypeError("health monitor requires ComponentHealthRecord")
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("health assessment time must be finite")
        heartbeat_age = (
            None
            if record.last_heartbeat_at is None
            else max(0.0, current - record.last_heartbeat_at)
        )
        progress_age = (
            None
            if record.last_progress_at is None
            else max(0.0, current - record.last_progress_at)
        )
        if record.phase is LifecyclePhase.FAILED:
            classification = HealthClassification.FAILED
            reason = "component reported FAILED"
        elif record.phase is LifecyclePhase.STOPPED:
            classification = HealthClassification.STOPPED
            reason = "component stopped"
        elif record.phase is LifecyclePhase.STARTING:
            classification = HealthClassification.STARTING
            reason = "component is starting"
        elif record.phase is not LifecyclePhase.READY:
            classification = HealthClassification.UNKNOWN
            reason = "phase not health-classified"
        elif (
            record.heartbeat_interval_s is not None
            and heartbeat_age is None
        ):
            classification = HealthClassification.STALLED
            reason = "READY component has no heartbeat"
        elif (
            record.heartbeat_interval_s is not None
            and heartbeat_age is not None
            and heartbeat_age
            > record.heartbeat_interval_s
            * self.heartbeat_grace_multiplier
        ):
            classification = HealthClassification.STALLED
            reason = "heartbeat expired"
        elif (
            self.progress_stall_s is not None
            and progress_age is not None
            and progress_age > self.progress_stall_s
        ):
            classification = HealthClassification.STALLED
            reason = "progress heartbeat expired"
        else:
            classification = HealthClassification.READY
            reason = "healthy"

        return HealthAssessment(
            record.component_id,
            classification,
            record.phase,
            heartbeat_age,
            progress_age,
            record.last_failure_id,
            reason,
        )


__all__ = [
    "ComponentHealthRecord",
    "ComponentHealthStore",
    "HealthAssessment",
    "HealthClassification",
    "HealthMonitor",
    "ResourceHealth",
]
