from __future__ import annotations

from dataclasses import dataclass

from .contracts import RuntimeLaunchManifestPort
from .control_plane import ServerRuntimeControlPlane
from .controller import RuntimeControlError, RuntimeControlReport
from .execution_guard import RecoveryLeaseRuntimeActionGuard
from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from noetrium_platform.infrastructure.reliability.recovery.api.ports import RecoveryExecutionFactoryPort, RecoveryExecutionPort
from .runtime_control_ports import RuntimeControlRecoveryPort
from .runtime_observer import (
    RuntimeLifecycleObserverPort,
    RuntimeObserverFailure,
    RuntimeObserverFailureSink,
    notify_runtime_observer,
)


@dataclass(frozen=True, slots=True)
class OneClickRuntimeReport:
    runtime: RuntimeControlReport
    history_verified: bool
    lease_owner: str
    history_reconciled: bool = False
    recovery_rounds: int = 0
    observer_failures: tuple[RuntimeObserverFailure, ...] = ()


class OneClickRuntimeManager:
    """Exact bootstrap/resume; observability is an injected fail-isolated side plane."""

    def __init__(
        self,
        plane: ServerRuntimeControlPlane,
        recovery: RecoveryExecutionFactoryPort,
        control_recovery: RuntimeControlRecoveryPort,
        *,
        max_recovery_rounds: int = 4,
    ) -> None:
        if max_recovery_rounds < 0:
            raise ValueError("max_recovery_rounds must be non-negative")
        self.plane = plane
        self.recovery = recovery
        self.control_recovery = control_recovery
        self.max_recovery_rounds = max_recovery_rounds

    @staticmethod
    def _observe(
        observer: RuntimeLifecycleObserverPort | None,
        failure_sink: RuntimeObserverFailureSink | None,
        failures: list[RuntimeObserverFailure],
        *,
        stage: str,
        callback,
    ) -> None:
        failure = notify_runtime_observer(observer, failure_sink, stage=stage, callback=callback)
        if failure is not None:
            failures.append(failure)

    def run_exact(
        self,
        manifest: RuntimeLaunchManifestPort,
        *,
        control_id: str,
        owner_id: str,
        ttl_seconds: float = 300.0,
        observer: RuntimeLifecycleObserverPort | None = None,
        observer_failure_sink: RuntimeObserverFailureSink | None = None,
    ) -> OneClickRuntimeReport:
        digest = manifest.digest()
        observer_failures: list[RuntimeObserverFailure] = []
        self._observe(
            observer,
            observer_failure_sink,
            observer_failures,
            stage="lease_wait_started",
            callback=lambda: observer.lease_wait_started(),
        )
        execution = self.recovery.execution(owner_id, digest, ttl_seconds=ttl_seconds)
        entered = False
        try:
            with execution as active_execution:
                entered = True
                self._observe(
                    observer,
                    observer_failure_sink,
                    observer_failures,
                    stage="lease_acquired",
                    callback=lambda: observer.lease_acquired(),
                )
                return self._run_owned(
                    active_execution,
                    manifest,
                    control_id=control_id,
                    owner_id=owner_id,
                    observer=observer,
                    observer_failure_sink=observer_failure_sink,
                    observer_failures=observer_failures,
                )
        except RecoveryLeaseBusy:
            if not entered:
                self._observe(
                    observer,
                    observer_failure_sink,
                    observer_failures,
                    stage="lease_conflict",
                    callback=lambda: observer.lease_conflict(),
                )
            raise

    def _run_owned(
        self,
        execution: RecoveryExecutionPort,
        manifest: RuntimeLaunchManifestPort,
        *,
        control_id: str,
        owner_id: str,
        observer: RuntimeLifecycleObserverPort | None,
        observer_failure_sink: RuntimeObserverFailureSink | None,
        observer_failures: list[RuntimeObserverFailure],
    ) -> OneClickRuntimeReport:
        history_reconciled = self.control_recovery.reconcile_history()

        recovery_rounds = 0
        action_guard = RecoveryLeaseRuntimeActionGuard(execution)
        failed_attempt_observer_failures: list[RuntimeObserverFailure] = []
        while True:
            try:
                report = self.plane.run_exact(
                    manifest,
                    control_id=control_id,
                    action_guard=action_guard,
                    observer=observer,
                    observer_failure_sink=observer_failure_sink,
                )
                break
            except RuntimeControlError as exc:
                failed_attempt_observer_failures.extend(exc.observer_failures)
                if not exc.recovery_required or recovery_rounds >= self.max_recovery_rounds:
                    raise
                recovery_rounds += 1
                self._observe(
                    observer,
                    observer_failure_sink,
                    observer_failures,
                    stage=f"recovery_round:{exc.action.value}:{recovery_rounds}",
                    callback=lambda exc=exc, recovery_rounds=recovery_rounds: observer.recovery_round(
                        exc.action,
                        round_number=recovery_rounds,
                    ),
                )
                execution.renew()

        execution.assert_owned()
        self.control_recovery.assert_history_tail_matches(report.state)
        combined_observer_failures = (
            tuple(observer_failures)
            + tuple(failed_attempt_observer_failures)
            + report.observer_failures
        )
        return OneClickRuntimeReport(
            report,
            True,
            owner_id,
            history_reconciled,
            recovery_rounds,
            combined_observer_failures,
        )
