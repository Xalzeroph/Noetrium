from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum



class LifecyclePhase(StrEnum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


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



__all__ = [
    "LifecycleEvidence",
    "LifecyclePhase",
]
