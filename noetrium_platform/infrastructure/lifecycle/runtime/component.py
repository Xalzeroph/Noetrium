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
    LifecycleComponent,
    LifecycleEvidence,
    LifecyclePhase,
    LifecycleSpec,
)


class LifecycleGraphError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RollbackFailure:
    component_id: str
    error_type: str
    error: str


class LifecycleStartError(RuntimeError):
    def __init__(
        self,
        component_id: str,
        cause: BaseException,
        started: tuple[str, ...],
        rollback_failures: tuple[RollbackFailure, ...],
    ) -> None:
        super().__init__(
            f"component start failed: {component_id}: "
            f"{type(cause).__name__}: {cause}"
        )
        self.component_id = component_id
        self.cause = cause
        self.started = started
        self.rollback_failures = rollback_failures


class LifecycleStopError(RuntimeError):
    def __init__(self, failures: tuple[RollbackFailure, ...]) -> None:
        super().__init__(f"component stop failures: {len(failures)}")
        self.failures = failures


@dataclass(frozen=True, slots=True)
class LifecycleRunReport:
    start_order: tuple[str, ...]
    evidence: tuple[LifecycleEvidence, ...]


class LifecycleExecutor:
    """Infrastructure-only dependency-ordered start/stop executor.

    This is provider/lifecycle mechanics, not research execution semantics.
    It owns no scientific state and no Machine Journal.
    """

    def __init__(self, components: tuple[LifecycleComponent, ...]) -> None:
        if type(components) is not tuple:
            raise TypeError("lifecycle components must be a tuple")
        mapping = {
            component.lifecycle_spec.component_id: component
            for component in components
        }
        if len(mapping) != len(components):
            raise LifecycleGraphError("duplicate lifecycle component id")
        self._components = mapping
        self._order = self._topological_order(
            tuple(component.lifecycle_spec for component in components)
        )

    @property
    def order(self) -> tuple[str, ...]:
        return self._order

    @staticmethod
    def _topological_order(
        specs: tuple[LifecycleSpec, ...],
    ) -> tuple[str, ...]:
        ids = {spec.component_id for spec in specs}
        indegree = {
            spec.component_id: len(spec.depends_on)
            for spec in specs
        }
        children = {spec.component_id: [] for spec in specs}
        for spec in specs:
            missing = set(spec.depends_on) - ids
            if missing:
                raise LifecycleGraphError(
                    f"component {spec.component_id} missing dependencies: "
                    f"{sorted(missing)}"
                )
            for dependency in spec.depends_on:
                children[dependency].append(spec.component_id)

        ready = [
            component_id
            for component_id, degree in indegree.items()
            if degree == 0
        ]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            component_id = heapq.heappop(ready)
            order.append(component_id)
            for child in children[component_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    heapq.heappush(ready, child)
        if len(order) != len(specs):
            cycle = sorted(
                component_id
                for component_id, degree in indegree.items()
                if degree
            )
            raise LifecycleGraphError(
                f"lifecycle dependency cycle among: {cycle}"
            )
        return tuple(order)

    def start_all(self, context: ExecutionContext) -> LifecycleRunReport:
        if not isinstance(context, ExecutionContext):
            raise TypeError("lifecycle start requires ExecutionContext")
        started: list[str] = []
        evidence: list[LifecycleEvidence] = []
        for component_id in self._order:
            component = self._components[component_id]
            evidence.append(
                LifecycleEvidence(component_id, LifecyclePhase.STARTING)
            )
            try:
                refs = tuple(
                    component.start(
                        context.child(
                            span_id=f"lifecycle:start:{component_id}",
                            component_id=component_id,
                        )
                    )
                )
            except Exception as exc:
                rollback: list[RollbackFailure] = []
                for previous in reversed(started):
                    try:
                        self._components[previous].stop(
                            context.child(
                                span_id=f"lifecycle:rollback:{previous}",
                                component_id=previous,
                            )
                        )
                    except Exception as rollback_exc:
                        rollback.append(
                            RollbackFailure(
                                previous,
                                type(rollback_exc).__name__,
                                str(rollback_exc),
                            )
                        )
                raise LifecycleStartError(
                    component_id,
                    exc,
                    tuple(started),
                    tuple(rollback),
                ) from exc
            started.append(component_id)
            evidence.append(
                LifecycleEvidence(
                    component_id,
                    LifecyclePhase.READY,
                    refs,
                )
            )
        return LifecycleRunReport(self._order, tuple(evidence))

    def stop_all(
        self,
        context: ExecutionContext,
    ) -> tuple[LifecycleEvidence, ...]:
        if not isinstance(context, ExecutionContext):
            raise TypeError("lifecycle stop requires ExecutionContext")
        evidence: list[LifecycleEvidence] = []
        failures: list[RollbackFailure] = []
        for component_id in reversed(self._order):
            evidence.append(
                LifecycleEvidence(component_id, LifecyclePhase.STOPPING)
            )
            try:
                refs = tuple(
                    self._components[component_id].stop(
                        context.child(
                            span_id=f"lifecycle:stop:{component_id}",
                            component_id=component_id,
                        )
                    )
                )
            except Exception as exc:
                failures.append(
                    RollbackFailure(
                        component_id,
                        type(exc).__name__,
                        str(exc),
                    )
                )
                evidence.append(
                    LifecycleEvidence(component_id, LifecyclePhase.FAILED)
                )
            else:
                evidence.append(
                    LifecycleEvidence(
                        component_id,
                        LifecyclePhase.STOPPED,
                        refs,
                    )
                )
        if failures:
            raise LifecycleStopError(tuple(failures))
        return tuple(evidence)


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
    "LifecycleExecutor",
    "LifecycleGraphError",
    "LifecycleRunReport",
    "LifecycleStartError",
    "LifecycleStopError",
    "ResourceHealth",
    "RollbackFailure",
]
