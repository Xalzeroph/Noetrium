from __future__ import annotations

from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    OperationResult,
)
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.runtime.program import (
    RunMachineBinding,
    RunMachineSession,
)

from ..api import RunCycleExecutorPort, RunSessionPort
from .closer import RunCloser
from .session import RunSession


class DefaultRunSessionFactory:
    """Construct RunSession with one shared journal-backed RunMachine authority."""

    def __init__(
        self,
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        self._journal = journal if journal is not None else InMemoryMachineJournal()
        self._snapshot_store = snapshot_store

    def create(
        self,
        *,
        spec: ExperimentSpec,
        identity: RunIdentity,
        cycle_executor: RunCycleExecutorPort,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        participant_lifecycle: ParticipantSessionLifecyclePort,
        open_operations: tuple[OperationResult[JsonValue], ...],
        initial_context: ExecutionContext,
    ) -> RunSessionPort:
        closer = RunCloser(
            spec=spec,
            identity=identity,
            participant_sessions=participant_sessions,
            lifecycle=participant_lifecycle,
        )
        run_machine = RunMachineSession.open(
            binding=RunMachineBinding(
                identity=identity,
                experiment_spec_digest=spec.identity_digest(),
            ),
            initial_context=initial_context,
            journal=self._journal,
            snapshot_store=self._snapshot_store,
        )
        if run_machine.phase.value == "created":
            run_machine.control_running(
                operation_id=canonical_digest({
                    "run_id": identity.run_id,
                    "event": "lifecycle-opened",
                }),
            )
        return RunSession(
            spec=spec,
            identity=identity,
            cycle_executor=cycle_executor,
            closer=closer,
            run_machine=run_machine,
            open_operations=open_operations,
            initial_context=initial_context,
        )


__all__ = ["DefaultRunSessionFactory"]
