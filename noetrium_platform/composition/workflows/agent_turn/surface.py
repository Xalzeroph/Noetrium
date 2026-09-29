from __future__ import annotations

from noetrium_platform.research.execution.capability.runtime import (
    CapabilityInvocationPipelineFactory,
)
from noetrium_platform.research.execution.capability.api import (
    RegistrationScopeFactoryPort,
)
from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceBindingContext

from .agent_turn_operations import AgentTurnTrialOperations


class AgentTurnSurfaceFactory:
    surface_id = "agent_turn.operations.v1"
    reuse_scope = "run"

    def __init__(
        self,
        registration_scope_factory: RegistrationScopeFactoryPort,
    ) -> None:
        self._registration_scope_factory = registration_scope_factory

    def bind(self, context: WorkflowSurfaceBindingContext) -> AgentTurnTrialOperations:
        if context.machine_journal is None:
            raise RuntimeError(
                "agent-turn surface requires shared MachineJournal authority"
            )
        capability_pipeline_factory = CapabilityInvocationPipelineFactory(
            context.machine_journal,
            snapshot_store=context.machine_snapshot_store,
        )
        return AgentTurnTrialOperations(
            context.dispatcher,
            context.participant_sessions,
            effect_dispatcher=context.effect_dispatcher,
            effect_intents=context.effect_intents,
            capability_pipeline_factory=capability_pipeline_factory,
            registration_scope_factory=self._registration_scope_factory,
        )


__all__ = ["AgentTurnSurfaceFactory"]
