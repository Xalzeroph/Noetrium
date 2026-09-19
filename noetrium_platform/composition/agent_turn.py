from __future__ import annotations

from noetrium_platform.composition.experiment_runtime import build_experiment_runtime
from noetrium_platform.composition.operation_forensics import CoreOperationFailureClassifier, OperationFailureClassifierChain
from noetrium_platform.composition.participants.agent import agent_participant_adapter
from noetrium_platform.composition.participants.capability import capability_participant_adapter
from noetrium_platform.composition.participants.generic import generic_participant_adapter
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import OperationExecutor
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.checkpoint import RunCheckpointStore
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentityProvider
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapter
from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceFactory
from noetrium_platform.research.execution.workflow.implementations.agent_turn import AgentTurnSurfaceFactory, agent_turn_trial_protocol
from noetrium_platform.research.execution.workflow.implementations.agent_turn.failure_classifier import AgentTurnFailureClassifier
from noetrium_platform.research.execution.capability.runtime import (
    ScopedRegistrationRuntimeFactory,
)
from noetrium_platform.research.execution.machines import (
    CapabilityMediatorRegistryPort,
    CapabilityProgram,
)


def agent_turn_participant_adapters(
    resolver: ParticipantResolverPort,
    *,
    runtime_kinds: tuple[str, ...] = (),
    include_capability_provider: bool = True,
    extra: tuple[ParticipantLifecycleAdapter, ...] = (),
) -> tuple[ParticipantLifecycleAdapter, ...]:
    rows: list[ParticipantLifecycleAdapter] = [agent_participant_adapter(resolver)]
    if include_capability_provider:
        rows.append(capability_participant_adapter(resolver))
    rows.extend(generic_participant_adapter(kind, resolver) for kind in runtime_kinds)
    rows.extend(extra)
    return tuple(rows)


def agent_turn_failure_classifier_chain() -> OperationFailureClassifierChain:
    return OperationFailureClassifierChain((AgentTurnFailureClassifier(), CoreOperationFailureClassifier()))


def compose_agent_turn_runtime(
    resolver: ParticipantResolverPort,
    *,
    runtime_kinds: tuple[str, ...] = (),
    include_capability_provider: bool = True,
    services: object = None,
    operation_executor: OperationExecutor | None = None,
    cycle_identity_provider: DecisionCycleIdentityProvider | None = None,
    effect_journal: EffectIntentJournal | None = None,
    checkpoint_store: RunCheckpointStore | None = None,
    extra_participant_adapters: tuple[ParticipantLifecycleAdapter, ...] = (),
    extra_surface_factories: tuple[WorkflowSurfaceFactory, ...] = (),
    capability_program: CapabilityProgram | None = None,
    capability_mediators: CapabilityMediatorRegistryPort | None = None,
) -> ExperimentRuntime:
    return build_experiment_runtime(
        participant_adapters=agent_turn_participant_adapters(
            resolver,
            runtime_kinds=runtime_kinds,
            include_capability_provider=include_capability_provider,
            extra=extra_participant_adapters,
        ),
        trial_protocol=agent_turn_trial_protocol(),
        workflow_surface_factories=(
            AgentTurnSurfaceFactory(
                ScopedRegistrationRuntimeFactory(),
                capability_program=capability_program,
                capability_mediators=capability_mediators,
            ),
            *extra_surface_factories,
        ),
        services=services,
        operation_executor=operation_executor,
        cycle_identity_provider=cycle_identity_provider,
        effect_journal=effect_journal,
        checkpoint_store=checkpoint_store,
    )


__all__ = [
    "agent_turn_failure_classifier_chain",
    "agent_turn_participant_adapters",
    "compose_agent_turn_runtime",
]
