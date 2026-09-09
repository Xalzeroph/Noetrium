from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding

from .dispatch import OperationDispatchPort
from .effect_intents import EffectIntentOperationPort


@dataclass(frozen=True, slots=True)
class WorkflowSurfaceBindingContext:
    dispatcher: OperationDispatchPort
    bound: BoundParticipants
    participant_sessions: tuple[ParticipantSessionBinding, ...]
    effect_intents: EffectIntentOperationPort | None = None


class WorkflowSurfaceReuseScope(StrEnum):
    """Lifetime for a workflow surface binding.

    ``cycle`` is the compatibility-safe default for stateful or unknown
    downstream surfaces.  ``run`` is appropriate only when the surface owns
    run-scoped collaborators and keeps no decision-cycle input in its
    constructor.
    """

    CYCLE = "cycle"
    RUN = "run"


@runtime_checkable
class WorkflowSurfaceFactory(Protocol):
    surface_id: str

    def bind(self, context: WorkflowSurfaceBindingContext) -> object: ...


def workflow_surface_reuse_scope(factory: WorkflowSurfaceFactory) -> WorkflowSurfaceReuseScope:
    """Resolve the explicitly declared binding lifetime for one surface factory."""

    value = getattr(factory, "reuse_scope", WorkflowSurfaceReuseScope.CYCLE)
    try:
        return value if isinstance(value, WorkflowSurfaceReuseScope) else WorkflowSurfaceReuseScope(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"workflow surface {getattr(factory, 'surface_id', '<unknown>')!r} "
            "declares an invalid reuse_scope; expected 'cycle' or 'run'"
        ) from exc


def workflow_surface_id(workflow: object) -> str:
    value = getattr(workflow, "surface_id", None)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workflow must declare a non-empty surface_id")
    return value


__all__ = [
    "WorkflowSurfaceBindingContext",
    "WorkflowSurfaceFactory",
    "WorkflowSurfaceReuseScope",
    "workflow_surface_reuse_scope",
    "workflow_surface_id",
]
