from __future__ import annotations

from noetrium_platform.composition.experiment_runtime import build_experiment_runtime
from noetrium_platform.composition.operation_forensics import CoreOperationFailureClassifier, OperationFailureClassifierChain
from noetrium_platform.composition.participants.environment import environment_participant_adapter
from noetrium_platform.composition.participants.method import method_participant_adapter
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import OperationExecutor
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.checkpoint import RunCheckpointStore
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentityProvider
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapter
from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceFactory
from noetrium_platform.research.execution.workflow.implementations.context_action import ContextActionSurfaceFactory, context_action_trial_protocol
from noetrium_platform.research.execution.workflow.implementations.context_action.failure_classifier import ContextActionFailureClassifier


def context_action_participant_adapters(
    resolver: ParticipantResolverPort,
    *,
    extra: tuple[ParticipantLifecycleAdapter, ...] = (),
) -> tuple[ParticipantLifecycleAdapter, ...]:
    return (method_participant_adapter(resolver), environment_participant_adapter(resolver), *extra)


def context_action_failure_classifier_chain() -> OperationFailureClassifierChain:
    return OperationFailureClassifierChain((ContextActionFailureClassifier(), CoreOperationFailureClassifier()))


def compose_context_action_runtime(
    resolver: ParticipantResolverPort,
    *,
    services: object = None,
    operation_executor: OperationExecutor | None = None,
    cycle_identity_provider: DecisionCycleIdentityProvider | None = None,
    effect_journal: EffectIntentJournal | None = None,
    checkpoint_store: RunCheckpointStore | None = None,
    extra_participant_adapters: tuple[ParticipantLifecycleAdapter, ...] = (),
    extra_surface_factories: tuple[WorkflowSurfaceFactory, ...] = (),
) -> ExperimentRuntime:
    return build_experiment_runtime(
        participant_adapters=context_action_participant_adapters(resolver, extra=extra_participant_adapters),
        trial_protocol=context_action_trial_protocol(),
        workflow_surface_factories=(ContextActionSurfaceFactory(), *extra_surface_factories),
        services=services,
        operation_executor=operation_executor,
        cycle_identity_provider=cycle_identity_provider,
        effect_journal=effect_journal,
        checkpoint_store=checkpoint_store,
    )


__all__ = [
    "compose_context_action_runtime",
    "context_action_failure_classifier_chain",
    "context_action_participant_adapters",
]
