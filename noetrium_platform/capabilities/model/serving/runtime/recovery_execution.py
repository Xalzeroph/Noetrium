from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..api.recovery import RecoveryPlan, RecoveryStep
from .recovery_transaction import RecoveryTransaction, RecoveryTxnState


class RecoveryStepExecutor(Protocol):
    def run_step(self, step: RecoveryStep, plan: RecoveryPlan) -> tuple[str, ...]: ...


class RecoveryExecutionError(RuntimeError):
    def __init__(
        self,
        step: RecoveryStep,
        cause: BaseException,
        completed: tuple[RecoveryStep, ...],
    ) -> None:
        super().__init__(f"model recovery execution failed at step {step.value}")
        self.step = step
        self.cause = cause
        self.completed = completed

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return (f"model-recovery-step:{self.step.value}",)


@dataclass(frozen=True, slots=True)
class RecoveryStepEvidence:
    step: RecoveryStep
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryExecutionReport:
    source_run_id: str
    state: RecoveryTxnState
    completed: tuple[RecoveryStepEvidence, ...]


class ExactRecoveryCoordinator:
    """Execute the immutable model recovery plan once, in declared order."""

    def __init__(self, executor: RecoveryStepExecutor) -> None:
        self._executor = executor

    def run(self, plan: RecoveryPlan) -> RecoveryExecutionReport:
        txn = RecoveryTransaction(plan)
        txn.start()
        evidence: list[RecoveryStepEvidence] = []
        for step in plan.steps:
            try:
                refs = tuple(self._executor.run_step(step, plan))
            except Exception as exc:
                txn.fail(step)
                raise RecoveryExecutionError(step, exc, tuple(txn.completed_steps)) from exc
            txn.complete_step(step)
            evidence.append(RecoveryStepEvidence(step, refs))
        if txn.state is not RecoveryTxnState.SUCCEEDED:
            raise RuntimeError("model recovery plan ended without terminal success")
        return RecoveryExecutionReport(plan.source_run_id, txn.state, tuple(evidence))


__all__ = [
    "ExactRecoveryCoordinator",
    "RecoveryExecutionError",
    "RecoveryExecutionReport",
    "RecoveryStepEvidence",
    "RecoveryStepExecutor",
]
