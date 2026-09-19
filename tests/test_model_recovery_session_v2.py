import threading
import time
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.serving.api import RecoveryPlan, RecoveryStep
from noetrium_platform.capabilities.model.serving.providers.recovery_storage import FileDurableRecoveryStore
from noetrium_platform.capabilities.model.serving.runtime import DurableExactRecoveryRunner
from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _plan(*steps: RecoveryStep) -> RecoveryPlan:
    identity = ImmutableModelIdentity(
        "model", "repo/model", "rev", "engine", "1", "bfloat16", None, 4096
    )
    return RecoveryPlan("run", identity, "d" * 64, tuple(steps))


class _Cancellation:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return "recovery test cancelled" if self.cancelled else None

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def checkpoint(self) -> None:
        if self.cancelled:
            raise TaskCancelled(self.reason or "recovery cancelled")

    def cancel(self) -> None:
        self._event.set()


class _RecordingExecutor:
    def __init__(self, cancellation: _Cancellation | None = None) -> None:
        self.calls: list[RecoveryStep] = []
        self.cancellation = cancellation

    def run_step(self, step: RecoveryStep, plan: RecoveryPlan) -> tuple[str, ...]:
        del plan
        self.calls.append(step)
        if self.cancellation is not None and len(self.calls) == 1:
            self.cancellation.cancel()
        return (f"evidence:{step.value}",)


def _store(root: Path, name: str = "recovery") -> FileDurableRecoveryStore:
    return FileDurableRecoveryStore(
        root / f"{name}.json", guard_path=root / f"{name}.guard.lock"
    )


def test_pre_cancelled_recovery_does_not_create_durable_state(tmp_path: Path) -> None:
    cancellation = _Cancellation()
    cancellation.cancel()
    store = _store(tmp_path)
    executor = _RecordingExecutor()

    with pytest.raises(TaskCancelled):
        DurableExactRecoveryRunner(store, executor).run(
            _plan(RecoveryStep.VERIFY_ARTIFACTS),
            attempt_id="attempt",
            cancellation=cancellation,
        )

    assert executor.calls == []
    assert store.exists() is False


def test_step_boundary_cancellation_preserves_completed_prefix(tmp_path: Path) -> None:
    cancellation = _Cancellation()
    store = _store(tmp_path)
    executor = _RecordingExecutor(cancellation)
    plan = _plan(RecoveryStep.VERIFY_ARTIFACTS, RecoveryStep.VERIFY_MODEL_IDENTITY)

    with pytest.raises(TaskCancelled):
        DurableExactRecoveryRunner(store, executor).run(
            plan, attempt_id="attempt", cancellation=cancellation
        )

    attempt = store.load()
    assert executor.calls == [RecoveryStep.VERIFY_ARTIFACTS]
    assert attempt.completed_steps == (RecoveryStep.VERIFY_ARTIFACTS.value,)
    assert attempt.current_step == RecoveryStep.VERIFY_ARTIFACTS.value
    assert attempt.current_step_status == "completed"
    assert attempt.current_effect_certainty == "no_effect"


class _BlockingExecutor:
    def __init__(self) -> None:
        self.calls: list[RecoveryStep] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def run_step(self, step: RecoveryStep, plan: RecoveryPlan) -> tuple[str, ...]:
        del plan
        self.calls.append(step)
        self.started.set()
        if not self.release.wait(2.0):
            raise TimeoutError("test executor was not released")
        return (f"evidence:{step.value}",)


def test_same_recovery_file_has_one_transaction_owner(tmp_path: Path) -> None:
    first_store = _store(tmp_path)
    second_store = _store(tmp_path)
    first_executor = _BlockingExecutor()
    second_executor = _RecordingExecutor()
    plan = _plan(RecoveryStep.VERIFY_ARTIFACTS)
    failures: list[BaseException] = []

    def run_first() -> None:
        try:
            DurableExactRecoveryRunner(first_store, first_executor).run(plan, attempt_id="a")
        except BaseException as exc:
            failures.append(exc)

    def run_second() -> None:
        try:
            DurableExactRecoveryRunner(second_store, second_executor).run(plan, attempt_id="a")
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=run_first)
    second = threading.Thread(target=run_second)
    first.start()
    assert first_executor.started.wait(1.0)
    second.start()
    time.sleep(0.05)

    assert second.is_alive()
    assert second_executor.calls == []

    first_executor.release.set()
    first.join(2.0)
    second.join(2.0)

    assert not first.is_alive() and not second.is_alive()
    assert failures == []
    assert first_executor.calls == [RecoveryStep.VERIFY_ARTIFACTS]
    assert second_executor.calls == []
    assert second_store.load().phase.value == "succeeded"
