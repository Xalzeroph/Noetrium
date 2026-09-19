from __future__ import annotations

from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointCoordinatorPort
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentComponentBindingPort,
    ExperimentSpec,
    ExperimentTrialCycleExecutorPort,
)
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from .assembly import RunAssembly
from ..identity.api import RunIdentity
from .resources import RunResourceAcquirer
from .restore import RunRestoreInitializer
from ..lifecycle.api import RunSessionFactoryPort, RunSessionPort
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort


class RunCoordinator:
    """Coordinates acquire → optional restore → assembly for one long-lived run."""

    def __init__(
        self,
        binder: ExperimentComponentBindingPort,
        lifecycle: ParticipantSessionLifecyclePort,
        trial: ExperimentTrialCycleExecutorPort,
        checkpoint: RunCheckpointCoordinatorPort | None,
        session_factory: RunSessionFactoryPort,
    ) -> None:
        self._resources = RunResourceAcquirer(binder, lifecycle)
        self._restore = RunRestoreInitializer(checkpoint)
        self._assembly = RunAssembly(trial, lifecycle, checkpoint, session_factory)

    def open(
        self,
        spec: ExperimentSpec,
        identity: RunIdentity,
        *,
        restore_checkpoint_id: str | None = None,
        restore_cycle_identity: DecisionCycleIdentity | None = None,
    ) -> RunSessionPort:
        resources = self._resources.acquire(spec, identity)
        try:
            initialized = self._restore.initialize(
                resources,
                spec,
                identity,
                restore_checkpoint_id=restore_checkpoint_id,
                restore_cycle_identity=restore_cycle_identity,
            )
        except BaseException as exc:
            self._resources.rollback(
                resources,
                context=resources.context,
                identity=identity,
                primary=exc,
            )
            raise
        return self._assembly.build(
            spec=spec,
            identity=identity,
            resources=resources,
            initialized=initialized,
        )


__all__ = ["RunCoordinator"]
