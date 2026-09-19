from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantCheckpointRuntimePort
from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api.runtime_operations import participant_operation_type
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


class ParticipantCheckpointOperations:
    """Operation-instrumented capture/restore for any bound participant session."""

    def __init__(self, dispatcher: OperationDispatchPort, checkpoints: ParticipantCheckpointRuntimePort) -> None:
        self._dispatcher = dispatcher
        self._checkpoints = checkpoints

    @staticmethod
    def _scope(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    @staticmethod
    def _operation_id(scope: str, binding: ParticipantSessionBinding, verb: str) -> str:
        participant = binding.participant
        return f"{scope}:{participant.implementation.kind}.{verb}:{participant.role}"

    def capture(
        self,
        binding: ParticipantSessionBinding,
        context: ExecutionContext,
        *,
        session_id: str,
    ) -> tuple[ParticipantCheckpoint, OperationResult[JsonValue]]:
        participant = binding.participant
        scope = self._scope(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=self._operation_id(scope, binding, "checkpoint"),
            operation_type=participant_operation_type(participant.adapter.kind, "checkpoint"),
            target=participant.component,
            payload={
                "session_id": session_id,
                "role": participant.role,
                "plugin_id": participant.implementation.participant_id,
            },
            payload_schema="participant.checkpoint.capture.request.v1",
            handler=lambda request: self._checkpoints.capture(
                participant.adapter,
                participant.runtime,
                binding.session,
                session_id=session_id,
            ),
        )
        checkpoint = self._dispatcher.require(operation)
        if not isinstance(checkpoint, ParticipantCheckpoint):
            raise TypeError("participant checkpoint capture must return ParticipantCheckpoint")
        return checkpoint, operation

    def restore(
        self,
        binding: ParticipantSessionBinding,
        checkpoint: ParticipantCheckpoint,
        context: ExecutionContext,
        *,
        session_id: str,
    ) -> OperationResult[JsonValue]:
        participant = binding.participant
        scope = self._scope(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=self._operation_id(scope, binding, "restore"),
            operation_type=participant_operation_type(participant.adapter.kind, "restore"),
            target=participant.component,
            payload={
                "role": participant.role,
                "checkpoint_ref_digest": checkpoint.ref.digest(),
                "snapshot_sha256": checkpoint.ref.payload_sha256,
            },
            payload_schema="participant.checkpoint.restore.request.v1",
            idempotency_key=checkpoint.ref.digest(),
            handler=lambda request: self._checkpoints.restore(
                participant.adapter,
                participant.runtime,
                binding.session,
                checkpoint,
                session_id=session_id,
            ),
        )
        self._dispatcher.require(operation)
        return operation


__all__ = ["ParticipantCheckpointOperations"]
