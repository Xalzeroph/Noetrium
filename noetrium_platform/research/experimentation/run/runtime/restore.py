from __future__ import annotations

from dataclasses import dataclass, replace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointCoordinatorPort
from .decision_coordination import identity_context
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from ..identity.api import RunIdentity
from .resources import OpenRunResources
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


@dataclass(frozen=True, slots=True)
class RunInitialization:
    context: ExecutionContext
    operation_results: tuple[OperationResult[JsonValue], ...]


class RunRestoreInitializer:
    """Applies an optional exact joint-checkpoint restore to acquired run resources."""

    def __init__(self, checkpoint: RunCheckpointCoordinatorPort | None) -> None:
        self._checkpoint = checkpoint

    def initialize(
        self,
        resources: OpenRunResources,
        spec: ExperimentSpec,
        identity: RunIdentity,
        *,
        restore_checkpoint_id: str | None,
        restore_cycle_identity: DecisionCycleIdentity | None,
    ) -> RunInitialization:
        if restore_checkpoint_id is None:
            return RunInitialization(resources.context, ())
        if self._checkpoint is None:
            raise RuntimeError("restore requested but ExperimentRuntime has no checkpoint store")
        cycle_identity = self._require_restore_identity(identity, restore_cycle_identity)
        restore_context = identity_context(cycle_identity, spec)
        restored = self._checkpoint.restore(
            restore_checkpoint_id,
            spec=spec,
            bound=resources.bound,
            participant_sessions=resources.participant_sessions,
            context=restore_context,
            cycle_identity=cycle_identity,
        )
        generations = tuple(sorted(
            (ref.role, ref.generation)
            for ref in restored.bundle.manifest.participant_snapshots
            if ref.generation is not None
        ))
        context = replace(
            restore_context,
            checkpoint_id=restore_checkpoint_id,
            participant_generations=generations,
        )
        return RunInitialization(context, restored.operation_results)

    @staticmethod
    def _require_restore_identity(
        identity: RunIdentity,
        restore_cycle_identity: DecisionCycleIdentity | None,
    ) -> DecisionCycleIdentity:
        if restore_cycle_identity is None:
            raise ValueError("restore_cycle_identity is required for exact checkpoint recovery")
        expected = (identity.run_id, identity.session_id, identity.trace_id)
        actual = (
            restore_cycle_identity.run_id,
            restore_cycle_identity.session_id,
            restore_cycle_identity.trace_id,
        )
        if actual != expected:
            raise ValueError("restore cycle identity does not belong to requested run identity")
        return restore_cycle_identity


__all__ = ["RunInitialization", "RunRestoreInitializer"]
