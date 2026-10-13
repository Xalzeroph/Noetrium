from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .bound import BoundParticipant, ParticipantSessionBinding
from .checkpoint import ParticipantCheckpoint
from .contracts import ParticipantRuntimeBinding
from .lifecycle import ParticipantLifecycleAdapter
from .runtime import ParticipantRuntimeHandle


class ParticipantResolutionPort(Protocol):
    def resolve(
        self,
        binding: ParticipantRuntimeBinding,
        context: ExecutionContext,
    ) -> tuple[BoundParticipant, OperationResult[JsonValue]]: ...


class ParticipantSessionLifecyclePort(Protocol):
    def open_participant(
        self,
        participant: BoundParticipant,
        context: ExecutionContext,
        session_id: str,
    ) -> tuple[ParticipantSessionBinding, OperationResult[JsonValue]]: ...

    def close_participant(
        self,
        binding: ParticipantSessionBinding,
        context: ExecutionContext,
        session_id: str,
    ) -> OperationResult[JsonValue]: ...


class ParticipantCheckpointRuntimePort(Protocol):
    """Participant-owned checkpoint execution authority, injected into external orchestrators."""

    def capture(
        self,
        adapter: ParticipantLifecycleAdapter,
        participant: ParticipantRuntimeHandle,
        session: object,
        *,
        session_id: str,
    ) -> ParticipantCheckpoint: ...

    def restore(
        self,
        adapter: ParticipantLifecycleAdapter,
        participant: ParticipantRuntimeHandle,
        session: object,
        checkpoint: ParticipantCheckpoint,
        *,
        session_id: str,
    ) -> None: ...


class ParticipantCheckpointOperationsPort(Protocol):
    def capture(
        self,
        binding: ParticipantSessionBinding,
        context: ExecutionContext,
        *,
        session_id: str,
    ) -> tuple[ParticipantCheckpoint, OperationResult[JsonValue]]: ...

    def restore(
        self,
        binding: ParticipantSessionBinding,
        checkpoint: ParticipantCheckpoint,
        context: ExecutionContext,
        *,
        session_id: str,
    ) -> OperationResult[JsonValue]: ...


__all__ = [
    "ParticipantCheckpointOperationsPort",
    "ParticipantCheckpointRuntimePort",
    "ParticipantResolutionPort",
    "ParticipantSessionLifecyclePort",
]
