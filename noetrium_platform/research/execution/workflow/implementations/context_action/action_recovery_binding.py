from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, PendingEffectRecoveryRequired
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, action_request_digest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


class ActionRecoveryRequestBinder:
    """Rebuilds an Environment ActionRequest from durable generic EffectIntent evidence."""

    def __init__(self, dispatcher: OperationDispatchPort, bound: BoundParticipants) -> None:
        self._dispatcher = dispatcher
        self._environment_component = bound.component("environment")

    def bind(
        self,
        intent: EffectIntent,
        *,
        action_type: str,
        action_payload: object,
        current_context: ExecutionContext,
    ) -> tuple[ActionRequest, OperationResult[JsonValue]]:
        dc = current_context.decision_cycle_id or current_context.span_id
        payload = {"intent": intent, "action_type": action_type, "action_payload": action_payload}
        operation = self._dispatcher.dispatch(
            root_context=current_context,
            operation_id=f"{dc}:environment.action_recovery.bind_request",
            operation_type="environment.action_recovery.bind_request",
            target=self._environment_component,
            payload=payload,
            payload_schema="environment.action_recovery.bind_request.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._bind_payload(
                request.payload["intent"],
                action_type=str(request.payload["action_type"]),
                action_payload=request.payload["action_payload"],
                current_context=request.context,
            ),
        )
        return self._dispatcher.require(operation), operation

    @staticmethod
    def _bind_payload(
        intent: EffectIntent,
        *,
        action_type: str,
        action_payload: object,
        current_context: ExecutionContext,
    ) -> ActionRequest:
        stable = (
            current_context.run_id,
            current_context.study_id,
            current_context.lifetime_id,
            current_context.task_id,
            current_context.decision_cycle_id,
            current_context.checkpoint_id,
        )
        expected = (
            intent.run_id,
            intent.study_id,
            intent.lifetime_id,
            intent.task_id,
            intent.decision_cycle_id,
            intent.checkpoint_id,
        )
        if stable != expected:
            raise PendingEffectRecoveryRequired(
                f"action recovery source identity mismatch: current={stable!r} prepared={expected!r}"
            )
        source_context = current_context.with_generation("environment", intent.source_generation)
        candidate = ActionRequest(intent.request_id, action_type, action_payload, source_context)
        if action_request_digest(candidate) != intent.request_digest:
            raise PendingEffectRecoveryRequired(
                "action recovery request does not match the durable PREPARED semantic digest"
            )
        return candidate


__all__ = ["ActionRecoveryRequestBinder"]
