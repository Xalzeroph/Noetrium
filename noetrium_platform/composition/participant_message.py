from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentTurnFact,
    AgentTurnFactKind,
    ParticipantMessageRouteReceipt,
    ParticipantMessageRouteRequest,
    ParticipantMessageRouterPort,
    record_participant_message_dispatch,
)
from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import AgentTurnFactSink
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    OperationRequest,
    OperationResult,
)
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


PARTICIPANT_MESSAGE_ROUTE_OPERATION = "participant.message.route"


@dataclass(frozen=True, slots=True)
class ParticipantMessageOperationOutput:
    receipt: ParticipantMessageRouteReceipt
    effect: EffectReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ParticipantMessageRouteReceipt):
            raise TypeError("participant message operation receipt must be typed")
        if not isinstance(self.effect, EffectReceipt):
            raise TypeError("participant message operation effect must be typed")


class ParticipantMessageOperations:
    """Composition-owned wiring for participant message side effects.

    Participant topology/schedule defines causal intent, the router is a replaceable
    participant runtime provider, OperationDispatchPort owns effect execution, and
    Agent Turn facts are candidate facts for the enclosing Machine Journal. This
    composition layer owns no independent durable message ledger.
    """

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        target: ComponentIdentity,
        router: ParticipantMessageRouterPort,
        facts: AgentTurnFactSink,
    ) -> None:
        self._dispatcher = dispatcher
        self._target = target
        self._router = router
        self._facts = facts

    @staticmethod
    def _decision_cycle(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    @staticmethod
    def _idempotency_key(context: ExecutionContext, request: ParticipantMessageRouteRequest) -> str:
        binding = request.binding
        return (
            f"participant-message:{context.run_id}:"
            f"{binding.entry_digest}:{binding.content_digest}"
        )

    def route(
        self,
        request: ParticipantMessageRouteRequest,
        context: ExecutionContext,
        *,
        artifact_refs: tuple[str, ...] = (),
    ) -> tuple[
        ParticipantMessageRouteReceipt,
        OperationResult[ParticipantMessageOperationOutput],
        tuple[AgentTurnFact, AgentTurnFact],
    ]:
        if not isinstance(request, ParticipantMessageRouteRequest):
            raise TypeError("participant message operation request must be typed")
        if not isinstance(context, ExecutionContext):
            raise TypeError("participant message operation context must be ExecutionContext")

        dispatch_fact = record_participant_message_dispatch(
            self._facts,
            context=context,
            binding=request.binding,
            artifact_refs=artifact_refs,
        )
        decision_cycle = self._decision_cycle(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{decision_cycle}:participant.message.route:{request.binding.message_id}",
            operation_type=PARTICIPANT_MESSAGE_ROUTE_OPERATION,
            target=self._target,
            payload=request,
            payload_schema=request.schema_version,
            idempotency_key=self._idempotency_key(context, request),
            handler=self._execute,
            effect_projector=lambda output: (output.effect,),
        )
        output = self._dispatcher.require(operation)

        routed_payload = output.receipt.as_fact_payload(request.binding)
        routed_payload.update({
            "operation_id": operation.operation_id,
            "operation_invocation_id": operation.invocation_id,
            "operation_output_digest": operation.output_digest,
            "effect_id": output.effect.effect_id,
            "effect_certainty": output.effect.certainty.value,
        })
        routed_fact = self._facts.append(
            AgentTurnFactKind.EFFECT,
            context=context,
            payload=routed_payload,
            artifact_refs=artifact_refs,
        )
        return output.receipt, operation, (dispatch_fact, routed_fact)

    def _execute(
        self,
        envelope: OperationRequest[ParticipantMessageRouteRequest],
    ) -> ParticipantMessageOperationOutput:
        request = envelope.payload
        if not isinstance(request, ParticipantMessageRouteRequest):
            raise TypeError("participant message operation payload must be typed")
        receipt = self._router.route(request)
        effect = EffectReceipt(
            effect_id=f"participant-message-route:{receipt.receipt_digest}",
            request_digest=envelope.payload_digest,
            effect_class=EffectClass.NON_IDEMPOTENT,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=self._target.component_id,
            verification_required=False,
            provider_receipt=receipt.receipt_digest,
        )
        return ParticipantMessageOperationOutput(receipt=receipt, effect=effect)


__all__ = [
    "PARTICIPANT_MESSAGE_ROUTE_OPERATION",
    "ParticipantMessageOperationOutput",
    "ParticipantMessageOperations",
]
