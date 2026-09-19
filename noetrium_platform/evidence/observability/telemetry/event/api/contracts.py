from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventDefinition:
    name: str
    required_fields: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class RuntimeStage:
    stage_id: str
    component_id: str
    start_event: str
    success_event: str
    failure_event: str


__all__ = ["EventDefinition", "RuntimeStage"]
