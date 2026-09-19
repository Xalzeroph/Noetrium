from __future__ import annotations

from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapter
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from noetrium_platform.capabilities.participant.session.api import ParticipantCheckpointRuntimePort


class ParticipantCheckpointRuntime(ParticipantCheckpointRuntimePort):
    """Session authority for exact checkpoint capture/restore validation."""

    def capture(
        self,
        adapter: ParticipantLifecycleAdapter,
        participant: ParticipantRuntimeHandle,
        session: object,
        *,
        session_id: str,
    ) -> ParticipantCheckpoint:
        checkpoint = adapter.checkpoint(participant, session, session_id=session_id)
        if not isinstance(checkpoint, ParticipantCheckpoint):
            raise TypeError("ParticipantLifecycleAdapter.checkpoint must return ParticipantCheckpoint")
        checkpoint.verify(
            binding=participant.binding,
            component=adapter.actual_component(participant),
            session_id=session_id,
        )
        return checkpoint

    def restore(
        self,
        adapter: ParticipantLifecycleAdapter,
        participant: ParticipantRuntimeHandle,
        session: object,
        checkpoint: ParticipantCheckpoint,
        *,
        session_id: str,
    ) -> None:
        checkpoint.verify(
            binding=participant.binding,
            component=adapter.actual_component(participant),
            session_id=session_id,
        )
        adapter.restore(participant, session, checkpoint, session_id=session_id)


__all__ = ["ParticipantCheckpointRuntime"]
