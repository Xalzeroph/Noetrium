from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .contracts import (
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)


@runtime_checkable
class ParticipantSessionRuntime(Protocol):
    """Execution engine for participant sessions; contains no scientific implementation identity."""

    @property
    def runtime_identity(self) -> ParticipantSessionRuntimeIdentity: ...

    def open_session(
        self,
        implementation: object,
        *,
        session_id: str,
        services: object,
    ) -> object: ...


@runtime_checkable
class ParticipantRuntimeEndpoint(Protocol):
    """Resolved execution endpoint with one domain identity and frozen runtime identities.

    Domain packages define implementation/session semantics.  Participant runtime is
    the single owner of session lifecycle exposure to orchestration.
    """

    @property
    def implementation_identity(self): ...

    @property
    def runtime_identity(self) -> ParticipantSessionRuntimeIdentity: ...

    def open_session(self, *, session_id: str, services: object) -> object: ...


@dataclass(frozen=True, slots=True)
class ParticipantRuntimeHandle:
    binding: ParticipantRuntimeBinding
    endpoint: ParticipantRuntimeEndpoint


class ParticipantResolverPort(Protocol):
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle: ...


__all__ = [
    "ParticipantResolverPort",
    "ParticipantRuntimeEndpoint",
    "ParticipantRuntimeHandle",
    "ParticipantSessionRuntime",
]
