from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort
from noetrium_platform.foundation.kernel.kernel.errors import attempt_secondary_delivery

from ..api.recovery import RecoveryPlan, RecoveryStep
from ..api.recovery_observer import DurableRecoveryObserverFailureSink, DurableRecoveryObserverPort, RecoveryObserverFailure
from ..api.recovery_ports import DurableRecoveryStorePort
from ..api.recovery_state import (
    DurableRecoveryAttempt,
    DurableRecoveryPhase,
    begin_recovery_step,
    complete_recovery_step,
    decide_resume,
    fail_recovery_step,
    new_recovery_attempt,
    succeed_recovery,
)


class DurableRecoveryExecutor(Protocol):
    def run_step(self, step: RecoveryStep, plan: RecoveryPlan) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class DurableRecoveryReport:
    attempt: DurableRecoveryAttempt
    executed_steps: tuple[RecoveryStep, ...]
    observer_failures: tuple[RecoveryObserverFailure, ...] = ()


class DurableExactRecoveryRunner:
    """Crash-reconcilable recovery state machine; observability is an injected side plane."""

    def __init__(
        self,
        store: DurableRecoveryStorePort,
        executor: DurableRecoveryExecutor,
        *,
        observer: DurableRecoveryObserverPort | None = None,
        observer_failure_sink: DurableRecoveryObserverFailureSink | None = None,
    ) -> None:
        self.store = store
        self.executor = executor
        self.observer = observer
        self.observer_failure_sink = observer_failure_sink

    def _notify(self, stage: str, callback) -> RecoveryObserverFailure | None:
        if self.observer is None:
            return None
        try:
            callback()
            return None
        except Exception as exc:
            failure = RecoveryObserverFailure.from_exception(stage, exc)
            if self.observer_failure_sink is not None:
                attempt_secondary_delivery(lambda: self.observer_failure_sink.record(failure))
            return failure

    @staticmethod
    def _checkpoint(cancellation: CancellationTokenPort | None) -> None:
        if cancellation is not None:
            cancellation.checkpoint()

    def run(
        self,
        plan: RecoveryPlan,
        *,
        attempt_id: str,
        cancellation: CancellationTokenPort | None = None,
    ) -> DurableRecoveryReport:
        self._checkpoint(cancellation)
        with self.store.recovery_session():
            self._checkpoint(cancellation)
            return self._run_session(
                plan, attempt_id=attempt_id, cancellation=cancellation
            )

    def _run_session(
        self,
        plan: RecoveryPlan,
        *,
        attempt_id: str,
        cancellation: CancellationTokenPort | None,
    ) -> DurableRecoveryReport:
        """Advance each remaining recovery step with crash-safe prefix durability.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the number of remaining recovery steps; each step persists begin and terminal state around one external recovery effect so cancellation or process loss resumes from the exact completed prefix.
        """
        observer_failures: list[RecoveryObserverFailure] = []
        existed = self.store.exists()
        cause = "resume" if existed else "initial"
        failure = self._notify("attempt_started", lambda: self.observer.attempt_started(cause=cause))
        if failure is not None:
            observer_failures.append(failure)
        if existed:
            attempt = self.store.load()
        else:
            attempt = new_recovery_attempt(attempt_id, plan, now=time.time())
            self.store.create(attempt)

        decision = decide_resume(attempt, plan)
        executed: list[RecoveryStep] = []
        if attempt.completed_steps != decision.completed_prefix:
            attempt = replace(
                attempt,
                completed_steps=decision.completed_prefix,
                current_step=None,
                current_step_status=None,
                current_effect_certainty=None,
                updated_at=time.time(),
            )
            self.store.write(attempt)

        try:
            for step in decision.steps:
                self._checkpoint(cancellation)
                attempt = begin_recovery_step(attempt, step, now=time.time())
                self.store.write(attempt)
                failure = self._notify(f"step_started:{step.value}", lambda step=step: self.observer.step_started(step))
                if failure is not None:
                    observer_failures.append(failure)
                try:
                    refs = tuple(self.executor.run_step(step, plan))
                except Exception:
                    failure = self._notify(f"step_finished:{step.value}:failed", lambda step=step: self.observer.step_finished(step, result="failed"))
                    if failure is not None:
                        observer_failures.append(failure)
                    attempt = fail_recovery_step(attempt, step, now=time.time())
                    self.store.write(attempt)
                    raise
                failure = self._notify(f"step_finished:{step.value}:success", lambda step=step: self.observer.step_finished(step, result="success"))
                if failure is not None:
                    observer_failures.append(failure)
                attempt = complete_recovery_step(attempt, step, refs, now=time.time())
                self.store.write(attempt)
                executed.append(step)

            if len(attempt.completed_steps) >= len(plan.steps):
                attempt = succeed_recovery(attempt, now=time.time())
                self.store.write(attempt)
            elif not decision.steps and attempt.phase != DurableRecoveryPhase.SUCCEEDED:
                raise RuntimeError("recovery made no progress but is not successful")
        except Exception:
            failure = self._notify("attempt_finished:failed", lambda: self.observer.attempt_finished(result="failed"))
            if failure is not None:
                observer_failures.append(failure)
            raise

        failure = self._notify("attempt_finished:success", lambda: self.observer.attempt_finished(result="success"))
        if failure is not None:
            observer_failures.append(failure)
        return DurableRecoveryReport(attempt, tuple(executed), tuple(observer_failures))


__all__ = ["DurableExactRecoveryRunner", "DurableRecoveryExecutor", "DurableRecoveryReport"]
