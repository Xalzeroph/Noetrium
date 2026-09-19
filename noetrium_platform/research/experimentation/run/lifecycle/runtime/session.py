from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonValue,
    OperationResult,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.decision.cycle_result import DecisionCycleResult
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.runtime.program import RunMachineSession

from ..api import RunCycleExecutorPort, RunLifetimePort
from ..api.contracts import RunCleanupFailure, RunCleanupReport


class RunSession:
    """Long-lived run facade over RunMachine authority and typed materializations."""

    def __init__(
        self,
        *,
        spec: ExperimentSpec,
        identity: RunIdentity,
        cycle_executor: RunCycleExecutorPort,
        lifetime: RunLifetimePort,
        run_machine: RunMachineSession,
        open_operations: tuple[OperationResult[JsonValue], ...],
        initial_context: ExecutionContext,
    ) -> None:
        if not isinstance(run_machine, RunMachineSession):
            raise TypeError("RunSession requires RunMachineSession")
        if run_machine.identity != identity:
            raise ValueError("RunSession RunMachine identity mismatch")
        if run_machine.binding.experiment_spec_digest != spec.identity_digest():
            raise ValueError("RunSession RunMachine ExperimentSpec mismatch")
        self.spec = spec
        self.identity = identity
        self.open_operations = open_operations
        self._cycle_executor = cycle_executor
        self._lifetime = lifetime
        self._run_machine = run_machine
        self._last_context = initial_context

    @property
    def last_context(self) -> ExecutionContext:
        return self._last_context

    @property
    def latest_checkpoint_id(self) -> str | None:
        return self._run_machine.latest_checkpoint_id

    @property
    def requires_recovery(self) -> bool:
        return self._run_machine.requires_recovery

    @property
    def completed_cycles(self) -> int:
        return self._run_machine.completed_cycles

    @property
    def closed(self) -> bool:
        return self._run_machine.closed

    @property
    def machine_cut(self):
        return self._run_machine.cut

    def execute(
        self,
        *,
        task: object,
        input_kind: str = "input",
        input_payload: object = None,
        cycle_identity: DecisionCycleIdentity,
    ) -> DecisionCycleResult:
        self._run_machine.require_runnable()
        cycle_id = cycle_identity.decision_cycle_id
        self._run_machine.cycle_started(cycle_id)
        try:
            execution = self._cycle_executor.execute(
                task=task,
                input_kind=input_kind,
                input_payload=input_payload,
                cycle_identity=cycle_identity,
                previous_context=self._last_context,
            )
        except BaseException as exc:
            failure = describe_exception(exc)
            self._run_machine.cycle_failed(
                cycle_id=cycle_id,
                failure_digest=failure.error_digest,
            )
            raise

        self._last_context = execution.final_context
        self._run_machine.cycle_completed(
            cycle_id=cycle_id,
            result_digest=canonical_digest(execution.result),
            final_context=execution.final_context,
            checkpoint_id=execution.checkpoint_id,
        )
        return execution.result

    def close(self) -> RunCleanupReport:
        if self._run_machine.closed:
            return RunCleanupReport(())
        try:
            report = self._lifetime.close(
                self._last_context,
                trial_completed=self._run_machine.completed_cycles > 0,
            )
        except BaseException as exc:
            if isinstance(exc, RunCleanupFailure):
                cleanup_digest = canonical_digest(exc.report.results)
            else:
                cleanup_digest = describe_exception(exc).error_digest
            self._run_machine.close(
                cleanup_succeeded=False,
                cleanup_digest=cleanup_digest,
            )
            raise
        self._run_machine.close(
            cleanup_succeeded=True,
            cleanup_digest=canonical_digest(report.results),
        )
        return report

    def __enter__(self) -> "RunSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.close()
        except BaseException as cleanup_exc:
            if exc is not None:
                try:
                    exc.add_note(f"study run close failure: {cleanup_exc}")
                except AttributeError:
                    pass
                return False
            raise
        return False


__all__ = ["RunSession"]
