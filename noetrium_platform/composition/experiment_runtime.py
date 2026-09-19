from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineJournalPort,
    MachineSnapshotStorePort,
    OperationExecutor,
)
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapter, ParticipantLifecycleAdapterRegistry
from noetrium_platform.research.experimentation.experiment.runtime import (
    ExperimentComponentBinder,
    ExperimentRuntime,
    ExperimentRuntimeComponents,
    ExperimentTrialCycleExecutor,
    trial_protocol_identity,
)
from noetrium_platform.capabilities.participant.session.runtime.checkpoint_runtime import ParticipantCheckpointRuntime
from noetrium_platform.research.execution.participants import (
    ParticipantCheckpointOperations,
    ParticipantResolutionOperations,
    ParticipantSessionLifecycle,
)
from noetrium_platform.research.experimentation.checkpoint.api.contracts import RunCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.runtime.coordination import RunCheckpointCoordinator
from noetrium_platform.research.experimentation.run.runtime.decision_runtime import DecisionCycleRuntime
from noetrium_platform.research.experimentation.run.identity.api import RunIdentityProvider
from noetrium_platform.research.experimentation.run.identity.providers import RandomRunIdentityProvider
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentityProvider, RandomDecisionCycleIdentityProvider
from noetrium_platform.research.experimentation.run.runtime.run_runtime import RunRuntime
from noetrium_platform.research.execution.workflow.runtime.program_trial import RuntimeProgramTrialProtocol
from noetrium_platform.research.execution.workflow.api import WorkflowSurfaceFactory
from noetrium_platform.research.execution.workflow.runtime import EffectIntentOperations, KernelOperationDispatcher, WORKFLOW_RUNTIME_IDENTITY


def build_experiment_runtime_components(
    *,
    participant_adapters: tuple[ParticipantLifecycleAdapter, ...],
    trial_protocol: RuntimeProgramTrialProtocol,
    workflow_surface_factories: tuple[WorkflowSurfaceFactory, ...],
    services: object = None,
    operation_executor: OperationExecutor | None = None,
    effect_journal: EffectIntentJournal | None = None,
    checkpoint_store: RunCheckpointStore | None = None,
    machine_journal: MachineJournalPort | None = None,
    machine_snapshot_store: MachineSnapshotStorePort | None = None,
) -> ExperimentRuntimeComponents:
    shared_machine_journal = (
        machine_journal
        if machine_journal is not None
        else InMemoryMachineJournal()
    )
    dispatcher = KernelOperationDispatcher(operation_executor or OperationExecutor(), caller=WORKFLOW_RUNTIME_IDENTITY)
    adapters = ParticipantLifecycleAdapterRegistry(participant_adapters)
    participant_resolution = ParticipantResolutionOperations(dispatcher, adapters)
    binder = ExperimentComponentBinder(participant_resolution)
    lifecycle = ParticipantSessionLifecycle(dispatcher, services)
    participant_checkpoints = ParticipantCheckpointOperations(dispatcher, ParticipantCheckpointRuntime())
    effect_intents = EffectIntentOperations(dispatcher, effect_journal) if effect_journal is not None else None
    trial_cycle = ExperimentTrialCycleExecutor(
        dispatcher,
        trial_protocol,
        effect_intents=effect_intents,
        workflow_surface_factories=workflow_surface_factories,
        machine_journal=shared_machine_journal,
        machine_snapshot_store=machine_snapshot_store,
    )
    checkpoint = (
        RunCheckpointCoordinator(dispatcher, checkpoint_store, participant_checkpoints)
        if checkpoint_store is not None
        else None
    )
    return ExperimentRuntimeComponents(
        trial_protocol_identity(trial_protocol),
        DecisionCycleRuntime(
            binder,
            lifecycle,
            trial_cycle,
            journal=shared_machine_journal,
            snapshot_store=machine_snapshot_store,
        ),
        RunRuntime(
            binder,
            lifecycle,
            trial_cycle,
            checkpoint,
            machine_journal=shared_machine_journal,
            machine_snapshot_store=machine_snapshot_store,
        ),
    )


def build_experiment_runtime(
    *,
    participant_adapters: tuple[ParticipantLifecycleAdapter, ...],
    trial_protocol: RuntimeProgramTrialProtocol,
    workflow_surface_factories: tuple[WorkflowSurfaceFactory, ...],
    services: object = None,
    operation_executor: OperationExecutor | None = None,
    cycle_identity_provider: DecisionCycleIdentityProvider | None = None,
    run_identity_provider: RunIdentityProvider | None = None,
    effect_journal: EffectIntentJournal | None = None,
    checkpoint_store: RunCheckpointStore | None = None,
    machine_journal: MachineJournalPort | None = None,
    machine_snapshot_store: MachineSnapshotStorePort | None = None,
) -> ExperimentRuntime:
    components = build_experiment_runtime_components(
        participant_adapters=participant_adapters,
        trial_protocol=trial_protocol,
        workflow_surface_factories=workflow_surface_factories,
        services=services,
        operation_executor=operation_executor,
        effect_journal=effect_journal,
        checkpoint_store=checkpoint_store,
        machine_journal=machine_journal,
        machine_snapshot_store=machine_snapshot_store,
    )
    return ExperimentRuntime(
        components,
        run_identity_provider=run_identity_provider or RandomRunIdentityProvider(),
        cycle_identity_provider=cycle_identity_provider or RandomDecisionCycleIdentityProvider(),
    )


__all__ = ["build_experiment_runtime", "build_experiment_runtime_components"]
