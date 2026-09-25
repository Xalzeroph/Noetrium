from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class LifecyclePhase(StrEnum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LifecycleSpec:
    """Infrastructure lifecycle contract for one operational component."""

    component_id: str
    depends_on: tuple[str, ...] = ()
    start_timeout_s: float = 120.0
    stop_timeout_s: float = 60.0
    heartbeat_interval_s: float | None = None

    def __post_init__(self) -> None:
        if type(self.component_id) is not str or not self.component_id.strip():
            raise ValueError("lifecycle component_id is required")
        if type(self.depends_on) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.depends_on
        ):
            raise TypeError("lifecycle depends_on must be a text tuple")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("lifecycle depends_on must be unique")
        if self.component_id in self.depends_on:
            raise ValueError("component cannot depend on itself")
        for name, value in (
            ("start_timeout_s", self.start_timeout_s),
            ("stop_timeout_s", self.stop_timeout_s),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.heartbeat_interval_s is not None:
            value = self.heartbeat_interval_s
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("heartbeat_interval_s must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(
                    "heartbeat_interval_s must be finite and positive"
                )


@dataclass(frozen=True, slots=True)
class LifecycleEvidence:
    component_id: str
    phase: LifecyclePhase
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.component_id) is not str or not self.component_id.strip():
            raise ValueError("lifecycle evidence component_id is required")
        if not isinstance(self.phase, LifecyclePhase):
            raise TypeError("lifecycle evidence phase must be LifecyclePhase")
        if type(self.refs) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.refs
        ):
            raise TypeError("lifecycle evidence refs must be a text tuple")


@runtime_checkable
class LifecycleComponent(Protocol):
    @property
    def lifecycle_spec(self) -> LifecycleSpec: ...

    def start(self, context: ExecutionContext) -> tuple[str, ...]: ...

    def stop(self, context: ExecutionContext) -> tuple[str, ...]: ...


__all__ = [
    "LifecycleComponent",
    "LifecycleEvidence",
    "LifecyclePhase",
    "LifecycleSpec",
]
