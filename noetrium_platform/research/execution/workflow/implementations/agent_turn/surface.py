from __future__ import annotations

from noetrium_platform.research.execution.capability.api import (
    CapabilityInvocationPipelineFactoryPort,
    RegistrationScopeFactoryPort,
)
from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceBindingContext

from .agent_turn_operations import AgentTurnTrialOperations


class AgentTurnSurfaceFactory:
    surface_id = "agent_turn.operations.v1"
    reuse_scope = "run"

    def __init__(
        self,
        capability_pipeline_factory: CapabilityInvocationPipelineFactoryPort,
        registration_scope_factory: RegistrationScopeFactoryPort,
    ) -> None:
        self._capability_pipeline_factory = capability_pipeline_factory
        self._registration_scope_factory = registration_scope_factory

    def bind(self, context: WorkflowSurfaceBindingContext) -> AgentTurnTrialOperations:
        return AgentTurnTrialOperations(
            context.dispatcher,
            context.participant_sessions,
            effect_intents=context.effect_intents,
            capability_pipeline_factory=self._capability_pipeline_factory,
            registration_scope_factory=self._registration_scope_factory,
        )


__all__ = ["AgentTurnSurfaceFactory"]
