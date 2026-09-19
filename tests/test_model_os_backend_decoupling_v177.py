from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import unittest

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import ModelPhase, ModelRunState, RecoveryPlan, RecoveryStep
from noetrium_platform.capabilities.model.serving.runtime import DurableExactRecoveryRunner, ModelSupervisor
from noetrium_platform.capabilities.model.serving.api.recovery_state import DurableRecoveryAttempt


class MemoryRecoveryStore:
    """Deliberately has no filesystem/path API."""

    def __init__(self) -> None:
        self.value: DurableRecoveryAttempt | None = None

    def recovery_session(self):
        return nullcontext()

    def exists(self) -> bool:
        return self.value is not None

    def create(self, attempt: DurableRecoveryAttempt) -> None:
        if self.value is not None:
            raise RuntimeError("already exists")
        self.value = attempt

    def write(self, attempt: DurableRecoveryAttempt) -> None:
        if self.value is None:
            raise RuntimeError("missing")
        self.value = attempt

    def load(self) -> DurableRecoveryAttempt:
        if self.value is None:
            raise RuntimeError("missing")
        return self.value


class RecordingRecoveryExecutor:
    def __init__(self) -> None:
        self.calls: list[RecoveryStep] = []

    def run_step(self, step: RecoveryStep, plan: RecoveryPlan) -> tuple[str, ...]:
        self.calls.append(step)
        return (f"memory:{step.value}",)


class MemoryModelStateStore:
    """Deliberately has no filesystem/path API."""

    def __init__(self) -> None:
        self.rows: list[ModelRunState] = []

    def write(self, state: ModelRunState) -> None:
        self.rows.append(state)


class ModelOSBackendDecouplingV177Tests(unittest.TestCase):
    @staticmethod
    def identity() -> ImmutableModelIdentity:
        return ImmutableModelIdentity("m", "repo/m", "rev", "engine", "1", "bfloat16", None, 4096)

    def test_exact_recovery_runner_needs_no_path_or_file_store(self) -> None:
        store = MemoryRecoveryStore()
        executor = RecordingRecoveryExecutor()
        plan = RecoveryPlan(
            source_run_id="run",
            frozen_identity=self.identity(),
            frozen_deployment_digest="d" * 64,
            steps=(RecoveryStep.VERIFY_ARTIFACTS, RecoveryStep.VERIFY_MODEL_IDENTITY),
        )
        report = DurableExactRecoveryRunner(store, executor).run(plan, attempt_id="attempt")
        self.assertEqual(report.executed_steps, plan.steps)
        self.assertEqual(executor.calls, list(plan.steps))
        self.assertEqual(report.attempt.phase.value, "succeeded")

    def test_model_supervisor_needs_only_state_store_port(self) -> None:
        store = MemoryModelStateStore()
        initial = ModelRunState.initial("run", self.identity(), "d" * 64)
        supervisor = ModelSupervisor(store, initial)
        next_state = supervisor.transition(ModelPhase.INVENTORY)
        self.assertEqual([row.phase for row in store.rows], [ModelPhase.NEW, ModelPhase.INVENTORY])
        self.assertIs(store.rows[-1], next_state)


if __name__ == "__main__":
    unittest.main()
