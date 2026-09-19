from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import BoundParticipant, ParticipantSessionBinding
from noetrium_platform.capabilities.participant.core.api.runtime_operations import participant_operation_type
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


class ParticipantSessionLifecycle:
    """Generic operation-instrumented participant session acquisition/release.

    This runtime service knows only frozen/bound participants and lifecycle adapters.
    Study/workflow semantics remain above this boundary.
    """

    def __init__(self, dispatcher: OperationDispatchPort, services: object = None) -> None:
        self._dispatcher = dispatcher
        self._services = services

    @staticmethod
    def _scope(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    @staticmethod
    def _operation_id(scope: str, participant: BoundParticipant, action: str) -> str:
        return f"{scope}:{participant.implementation.kind}.{action}:{participant.role}"

    def open_participant(
        self,
        participant: BoundParticipant,
        context: ExecutionContext,
        session_id: str,
    ) -> tuple[ParticipantSessionBinding, OperationResult[JsonValue]]:
        scope = self._scope(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=self._operation_id(scope, participant, "open_session"),
            operation_type=participant_operation_type(participant.adapter.kind, "open_session"),
            target=participant.component,
            payload={
                "session_id": session_id,
                "kind": participant.implementation.kind,
                "role": participant.role,
                "plugin_id": participant.implementation.participant_id,
            },
            payload_schema="participant.session.open.request.v1",
            handler=lambda request: participant.adapter.open_session(
                participant.runtime,
                session_id=session_id,
                services=self._services,
            ),
            digest_output=False,
        )
        return ParticipantSessionBinding(participant, self._dispatcher.require(operation)), operation

    def close_participant(
        self,
        binding: ParticipantSessionBinding,
        context: ExecutionContext,
        session_id: str,
    ) -> OperationResult[JsonValue]:
        scope = self._scope(context)
        participant = binding.participant
        return self._dispatcher.dispatch(
            root_context=context,
            operation_id=self._operation_id(scope, participant, "close"),
            operation_type=participant_operation_type(participant.adapter.kind, "close"),
            target=participant.component,
            payload={
                "session_id": session_id,
                "kind": participant.implementation.kind,
                "role": participant.role,
                "plugin_id": participant.implementation.participant_id,
            },
            payload_schema="participant.session.close.request.v1",
            handler=lambda request: participant.adapter.close_session(binding.session),
        )


__all__ = ["ParticipantSessionLifecycle"]
