from __future__ import annotations

from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointCoordinatorPort
from ..lifecycle.api import RunSessionFactoryPort, RunSessionPort
from .cycle import RunCycleExecutor
from ..identity.api import RunIdentity
from .resources import OpenRunResources
from .restore import RunInitialization
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentSpec,
    ExperimentTrialCycleExecutorPort,
)
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort


class RunAssembly:
    """Composition root for an already-acquired, already-initialized long-lived run."""

    def __init__(
        self,
        trial: ExperimentTrialCycleExecutorPort,
        lifecycle: ParticipantSessionLifecyclePort,
        checkpoint: RunCheckpointCoordinatorPort | None,
        session_factory: RunSessionFactoryPort,
    ) -> None:
        self._trial = trial
        self._lifecycle = lifecycle
        self._checkpoint = checkpoint
        self._session_factory = session_factory

    def build(
        self,
        *,
        spec: ExperimentSpec,
        identity: RunIdentity,
        resources: OpenRunResources,
        initialized: RunInitialization,
    ) -> RunSessionPort:
        cycle_executor = RunCycleExecutor(
            spec=spec,
            run_identity=identity,
            bound=resources.bound,
            trial=self._trial,
            checkpoint=self._checkpoint,
            participant_sessions=resources.participant_sessions,
        )
        return self._session_factory.create(
            spec=spec,
            identity=identity,
            cycle_executor=cycle_executor,
            participant_sessions=resources.participant_sessions,
            participant_lifecycle=self._lifecycle,
            open_operations=resources.operation_results + initialized.operation_results,
            initial_context=initialized.context,
        )


__all__ = ["RunAssembly"]
