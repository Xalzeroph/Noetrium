from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..api.recovery import RecoveryPlan, RecoveryStep


class RecoveryTxnState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class RecoveryTransaction:
    plan: RecoveryPlan
    state: RecoveryTxnState = RecoveryTxnState.PLANNED
    completed_steps: list[RecoveryStep] = field(default_factory=list)
    failed_step: RecoveryStep | None = None

    def start(self) -> None:
        if self.state != RecoveryTxnState.PLANNED:
            raise RuntimeError("recovery transaction already started")
        self.state = RecoveryTxnState.RUNNING

    def complete_step(self, step: RecoveryStep) -> None:
        if self.state != RecoveryTxnState.RUNNING:
            raise RuntimeError("transaction is not running")
        expected = self.plan.steps[len(self.completed_steps)]
        if step != expected:
            raise RuntimeError(f"recovery step out of order: expected {expected}, got {step}")
        self.completed_steps.append(step)
        if len(self.completed_steps) == len(self.plan.steps):
            self.state = RecoveryTxnState.SUCCEEDED

    def fail(self, step: RecoveryStep) -> None:
        if self.state != RecoveryTxnState.RUNNING:
            raise RuntimeError("transaction is not running")
        self.failed_step = step
        self.state = RecoveryTxnState.FAILED
