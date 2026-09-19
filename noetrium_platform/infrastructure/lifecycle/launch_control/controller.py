from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from .contracts import RuntimeAction, RuntimeLaunchManifestPort, RuntimePlan, RuntimeStep, exact_runtime_plan
from .execution_guard import RuntimeActionExecutionGuard
from .failure_policy import classify_runtime_failure
from .runtime_control_policy import resume_decision
from .runtime_control_ports import RuntimeControlTransactionPort
from .runtime_control_transitions import (
    begin_runtime_action,
    complete_runtime_action,
    fail_runtime_action,
    rewind_for_resume,
    succeed_runtime,
)
from .runtime_observer import (
    RuntimeControlObserverPort,
    RuntimeObserverFailure,
    RuntimeObserverFailureSink,
    notify_runtime_observer,
)
from .runtime_state_contracts import RuntimeControlState


class RuntimeControlAdapter(Protocol):
    def execute(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class RuntimeControlReport:
    state: RuntimeControlState
    executed_actions: tuple[RuntimeAction, ...]
    observer_failures: tuple[RuntimeObserverFailure, ...] = ()


class RuntimeControlError(RuntimeError):
    def __init__(
        self,
        action: RuntimeAction,
        cause: BaseException,
        recovery_required: bool,
        *,
        observer_failures: tuple[RuntimeObserverFailure, ...] = (),
    ):
        safe = describe_exception(cause)
        super().__init__(f"runtime action failed at {action.value}: {safe.error_type}: {safe.safe_message}")
        self.action = action
        self.cause = cause
        self.recovery_required = recovery_required
        self.error_digest = safe.error_digest
        self.observer_failures = observer_failures


class ExactRuntimeController:
    """Executes one exact plan; policy, state transitions, storage, and observability stay external."""

    def __init__(
        self,
        store: RuntimeControlTransactionPort,
        adapter: RuntimeControlAdapter,
        plan: RuntimePlan | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.plan = plan or exact_runtime_plan()

    @staticmethod
    def _observe(
        observer: RuntimeControlObserverPort | None,
        failure_sink: RuntimeObserverFailureSink | None,
        failures: list[RuntimeObserverFailure],
        *,
        stage: str,
        callback,
    ) -> None:
        failure = notify_runtime_observer(observer, failure_sink, stage=stage, callback=callback)
        if failure is not None:
            failures.append(failure)

    def _load_or_create(self, manifest: RuntimeLaunchManifestPort, control_id: str) -> RuntimeControlState:
        digest = manifest.digest()
        state = self.store.read() if self.store.exists() else self.store.create(control_id, digest)
        if state.manifest_digest != digest:
            raise ValueError("runtime control state belongs to a different frozen manifest")
        return state

    def _rewind_if_needed(
        self,
        state: RuntimeControlState,
        decision_steps: tuple[RuntimeStep, ...],
    ) -> RuntimeControlState:
        if not decision_steps:
            return state
        start_index = self.plan.steps.index(decision_steps[0])
        expected = tuple(step.action.value for step in self.plan.steps[:start_index])
        if state.completed_actions == expected:
            return state
        state = rewind_for_resume(state, completed_prefix=expected, now=time.time())
        self.store.write(state)
        return state

    def _execute_step(
        self,
        state: RuntimeControlState,
        step: RuntimeStep,
        manifest: RuntimeLaunchManifestPort,
        *,
        action_guard: RuntimeActionExecutionGuard | None,
        observer: RuntimeControlObserverPort | None,
        observer_failure_sink: RuntimeObserverFailureSink | None,
        observer_failures: list[RuntimeObserverFailure],
    ) -> tuple[RuntimeControlState, tuple[str, ...]]:
        if action_guard is not None:
            action_guard.before_action(step.action, manifest)
        state = begin_runtime_action(state, step, now=time.time())
        self.store.write(state)
        self._observe(
            observer,
            observer_failure_sink,
            observer_failures,
            stage=f"action_started:{step.action.value}",
            callback=lambda: observer.action_started(step.action, mutating=step.mutating),
        )
        try:
            refs = tuple(self.adapter.execute(step.action, manifest))
        except Exception as exc:
            self._observe(
                observer,
                observer_failure_sink,
                observer_failures,
                stage=f"action_finished:{step.action.value}:failed",
                callback=lambda: observer.action_finished(step.action, result="failed", mutating=step.mutating),
            )
            recovery_required = classify_runtime_failure(step, exc).recovery_required
            state = fail_runtime_action(
                state,
                recovery_required=recovery_required,
                error=describe_exception(exc),
                now=time.time(),
            )
            self.store.write(state)
            raise RuntimeControlError(
                step.action,
                exc,
                recovery_required,
                observer_failures=tuple(observer_failures),
            ) from exc
        if action_guard is not None:
            action_guard.after_success(step.action, manifest)
        self._observe_success(observer, observer_failure_sink, observer_failures, step)
        state = complete_runtime_action(state, step, refs, now=time.time())
        self.store.write(state)
        return state, refs

    def _observe_success(
        self,
        observer: RuntimeControlObserverPort | None,
        failure_sink: RuntimeObserverFailureSink | None,
        failures: list[RuntimeObserverFailure],
        step: RuntimeStep,
    ) -> None:
        self._observe(
            observer,
            failure_sink,
            failures,
            stage=f"action_finished:{step.action.value}:success",
            callback=lambda: observer.action_finished(step.action, result="success", mutating=step.mutating),
        )
        if step.action in {RuntimeAction.RECONCILE_SERVICES, RuntimeAction.RECONCILE_RUN}:
            scope = "services" if step.action == RuntimeAction.RECONCILE_SERVICES else "study"
            self._observe(
                observer,
                failure_sink,
                failures,
                stage=f"reconcile_finished:{scope}",
                callback=lambda: observer.reconcile_finished(scope=scope),
            )
        if step.action == RuntimeAction.START_EXACT_SERVICES:
            self._observe(
                observer,
                failure_sink,
                failures,
                stage="exact_service_started",
                callback=lambda: observer.exact_service_started(),
            )
        if step.action == RuntimeAction.VERIFY_RUNTIME_QUALIFICATION:
            self._observe(
                observer,
                failure_sink,
                failures,
                stage="qualification_verified",
                callback=lambda: observer.qualification_verified(),
            )

    def run(
        self,
        manifest: RuntimeLaunchManifestPort,
        *,
        control_id: str,
        action_guard: RuntimeActionExecutionGuard | None = None,
        observer: RuntimeControlObserverPort | None = None,
        observer_failure_sink: RuntimeObserverFailureSink | None = None,
    ) -> RuntimeControlReport:
        state = self._load_or_create(manifest, control_id)
        decision = resume_decision(state, self.plan)
        state = self._rewind_if_needed(state, decision.steps)
        executed: list[RuntimeAction] = []
        observer_failures: list[RuntimeObserverFailure] = []
        for step in decision.steps:
            state, _ = self._execute_step(
                state,
                step,
                manifest,
                action_guard=action_guard,
                observer=observer,
                observer_failure_sink=observer_failure_sink,
                observer_failures=observer_failures,
            )
            executed.append(step.action)
        state = succeed_runtime(state, now=time.time())
        self.store.write(state)
        return RuntimeControlReport(state, tuple(executed), tuple(observer_failures))


__all__ = [
    "ExactRuntimeController",
    "RuntimeControlAdapter",
    "RuntimeControlError",
    "RuntimeControlReport",
]
