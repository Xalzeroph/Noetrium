from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, JsonValue, OperationResult

from .contracts import ParticipantImplementationIdentity
from .lifecycle import ParticipantLifecycleAdapter
from .runtime import ParticipantRuntimeEndpoint, ParticipantRuntimeHandle


@dataclass(frozen=True, slots=True)
class BoundParticipant:
    """Runtime-bound participant with no ExperimentSpec/orchestration dependency."""

    role: str
    implementation: ParticipantImplementationIdentity
    runtime: ParticipantRuntimeHandle
    component: ComponentIdentity
    adapter: ParticipantLifecycleAdapter

    @property
    def endpoint(self) -> ParticipantRuntimeEndpoint:
        return self.runtime.endpoint


@dataclass(frozen=True, slots=True)
class BoundParticipants:
    participants: tuple[BoundParticipant, ...]
    operation_results: tuple[OperationResult[JsonValue], ...] = ()

    def participant(self, role: str) -> BoundParticipant:
        matches = tuple(row for row in self.participants if row.role == role)
        if len(matches) != 1:
            raise LookupError(f"expected exactly one participant for role={role!r}, found={len(matches)}")
        return matches[0]

    def optional_participant(self, role: str) -> BoundParticipant | None:
        matches = tuple(row for row in self.participants if row.role == role)
        if len(matches) > 1:
            raise LookupError(f"expected at most one participant for role={role!r}, found={len(matches)}")
        return matches[0] if matches else None

    def component(self, role: str) -> ComponentIdentity:
        return self.participant(role).component

    def endpoint(self, role: str) -> ParticipantRuntimeEndpoint:
        return self.participant(role).endpoint


@dataclass(frozen=True, slots=True)
class ParticipantSessionBinding:
    participant: BoundParticipant
    session: object

    @property
    def role(self) -> str:
        return self.participant.role


__all__ = ["BoundParticipant", "BoundParticipants", "ParticipantSessionBinding"]
