from __future__ import annotations

from typing import TYPE_CHECKING

from noetrium_platform.capabilities.participant.agent.api import AgentTurnRequest, AgentTurnResult
from noetrium_platform.capabilities.participant.capability.api import CapabilityExportSession
from noetrium_platform.research.execution.capability.api import (
    CapabilityInvocationPipelineFactoryPort,
    RegistrationScopeFactoryPort,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .capability_effects import CapabilityEffectExecutor
from .capability_operations import CapabilityOperationAdapter
from .capability_routing import CapabilitySessionBinding, StudyCapabilityRouter
from noetrium_platform.research.execution.workflow.api import (
    EffectIntentOperationPort,
    OperationDispatchPort,
    WorkflowParticipantRequirementError,
)
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding

if TYPE_CHECKING:
    from noetrium_platform.research.execution.machines.capability_program import (
        CapabilityProgramBinding,
    )


class AgentTurnTrialOperations:
    """Agent+Capability operation surface only; no Method/Environment action dependencies."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        *,
        effect_dispatcher: OperationDispatchPort | None = None,
        effect_intents: EffectIntentOperationPort | None = None,
        capability_pipeline_factory: CapabilityInvocationPipelineFactoryPort,
        registration_scope_factory: RegistrationScopeFactoryPort,
        capability_program: "CapabilityProgramBinding | None" = None,
    ) -> None:
        self._dispatcher = dispatcher
        agent = next(
            (row for row in participant_sessions if row.participant.role == "agent"),
            None,
        )
        if agent is None:
            raise WorkflowParticipantRequirementError("agent_turn workflow requires participant role: agent")
        self._agent = agent
        self._capability_sessions = tuple(
            CapabilitySessionBinding(
                row.participant.component,
                row.session,
                source_role=row.participant.role,
                participant=row.participant,
            )
            for row in participant_sessions
            if isinstance(row.session, CapabilityExportSession)
        )
        effect_operation_dispatcher = effect_dispatcher or dispatcher
        self._capability_operations = CapabilityOperationAdapter(
            effect_operation_dispatcher
        )
        self._capability_pipeline_factory = capability_pipeline_factory
        self._registration_scope_factory = registration_scope_factory
        self._capability_program = capability_program
        self._capability_effects = (
            CapabilityEffectExecutor(dispatcher, effect_intents, self._capability_operations)
            if effect_intents is not None else None
        )

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def agent_turn(
        self, task: object, input_payload: object, context: ExecutionContext
    ) -> tuple[AgentTurnResult, tuple[OperationResult[JsonValue], ...]]:
        router = StudyCapabilityRouter(
            self._capability_operations,
            self._capability_sessions,
            effect_executor=self._capability_effects,
            consumer_component=self._agent.participant.component,
            pipeline=self._capability_pipeline_factory.create(self._capability_program),
            scope=self._registration_scope_factory.create(
                f"decision-cycle:{self._dc(context)}:capabilities"
            ),
        )
        dc = self._dc(context)
        request = AgentTurnRequest(task, context, input_payload)
        try:
            operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:agent.run_turn",
            operation_type="agent.run_turn",
            target=self._agent.participant.component,
            payload=request,
            payload_schema="agent.turn.request.v1",
                handler=lambda envelope: self._agent.session.run_turn(
                    AgentTurnRequest(
                        envelope.payload.task,
                        envelope.context,
                        envelope.payload.input_payload,
                    ),
                    router,
                ),
            )
            result = self._dispatcher.require(operation)
            if not isinstance(result, AgentTurnResult):
                raise TypeError("AgentSession.run_turn must return AgentTurnResult")
            return result, router.drain_operations() + (operation,)
        finally:
            router.close()


__all__ = ["AgentTurnTrialOperations"]
