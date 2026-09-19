from __future__ import annotations

from dataclasses import dataclass, replace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointCoordinatorPort
from .decision_runtime import identity_context
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.decision.cycle_result import DecisionCycleResult
from ..identity.api import RunIdentity
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentSpec,
    ExperimentTrialCycleExecutorPort,
)


class RunIdentityMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunCycleExecution:
    result: DecisionCycleResult
    final_context: ExecutionContext
    checkpoint_id: str | None


class RunCycleExecutor:
    """Executes one trial cycle against an already-open participant topology."""

    def __init__(
        self,
        *,
        spec: ExperimentSpec,
        run_identity: RunIdentity,
        bound: BoundParticipants,
        trial: ExperimentTrialCycleExecutorPort,
        checkpoint: RunCheckpointCoordinatorPort | None,
        participant_sessions: tuple[ParticipantSessionBinding, ...] = (),
    ) -> None:
        self._spec = spec
        self._run_identity = run_identity
        self._bound = bound
        self._trial = trial
        self._checkpoint = checkpoint
        self._participant_sessions = participant_sessions

    def _validate_identity(self, identity: DecisionCycleIdentity) -> None:
        expected = (
            self._run_identity.run_id,
            self._run_identity.session_id,
            self._run_identity.trace_id,
        )
        actual = (identity.run_id, identity.session_id, identity.trace_id)
        if actual != expected:
            raise RunIdentityMismatch(
                f"cycle does not belong to open run: expected={expected!r} actual={actual!r}"
            )

    def _context(
        self,
        identity: DecisionCycleIdentity,
        previous: ExecutionContext | None,
    ) -> ExecutionContext:
        context = identity_context(identity, self._spec)
        if previous is None:
            return context
        return replace(
            context,
            checkpoint_id=previous.checkpoint_id,
            participant_generations=previous.participant_generations,
            platform_generation=previous.platform_generation,
        )

    def execute(
        self,
        *,
        task: object,
        input_kind: str,
        input_payload: object,
        cycle_identity: DecisionCycleIdentity,
        previous_context: ExecutionContext | None,
    ) -> RunCycleExecution:
        self._validate_identity(cycle_identity)
        context = self._context(cycle_identity, previous_context)
        trial = self._trial.execute(
            bound=self._bound,
            participant_sessions=self._participant_sessions,
            context=context,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
        )
        rows: list[OperationResult[JsonValue]] = list(trial.operation_results)
        final_context = trial.final_context
        checkpoint_id: str | None = None
        if self._checkpoint is not None:
            checkpoint = self._checkpoint.checkpoint(
                spec=self._spec,
                bound=self._bound,
                participant_sessions=self._participant_sessions,
                context=final_context,
                cycle_identity=cycle_identity,
            )
            rows.extend(checkpoint.operation_results)
            checkpoint_id = checkpoint.manifest.checkpoint_id
            final_context = replace(final_context, checkpoint_id=checkpoint_id)
        result = DecisionCycleResult(
            cycle_identity.run_id,
            cycle_identity.decision_cycle_id,
            trial.context_text,
            trial.primary_result,
            tuple(rows),
            cycle_identity,
        )
        return RunCycleExecution(result, final_context, checkpoint_id)


__all__ = ["RunCycleExecution", "RunCycleExecutor", "RunIdentityMismatch"]
