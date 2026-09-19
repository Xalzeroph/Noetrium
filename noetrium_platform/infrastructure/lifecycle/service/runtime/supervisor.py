from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceReconcileObservation,
)
from .contracts import ServiceExitClass
from .crash_capture import ServiceCrashEvidenceAdapter, ServiceCrashReport
from .service_crash_transition import ServiceCrashTransitionCoordinator
from .service_observation import ServiceObservationCoordinator
from .service_state_contracts import ServiceSupervisorState
from .service_stop import ServiceStopCoordinator
from .start_coordination import ServiceStartCoordinator
from .start_journal import ServiceStartJournal
from .state_ports import ServiceStateStorePort
from .state_transition import ServiceStateTransitionWriter
from .supervision_contracts import ServiceProcessAdapter, ServiceStartReport


class ExactServiceSupervisor:
    """Thin public façade over independent exact-service runtime authorities."""

    def __init__(
        self,
        store: ServiceStateStorePort,
        adapter: ServiceProcessAdapter,
        *,
        start_journal: ServiceStartJournal,
    ) -> None:
        observation = ServiceObservationCoordinator(store, adapter, start_journal)
        transitions = ServiceStateTransitionWriter(store)
        self._observation = observation
        self._start = ServiceStartCoordinator(store, adapter, start_journal)
        self._stop = ServiceStopCoordinator(observation, adapter, transitions)
        self._crash = ServiceCrashTransitionCoordinator(observation, transitions)

    def observe_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState | None:
        return self._observation.observe_state(contract)

    def reconcile_exact(self, contract: ServiceLaunchContract) -> ServiceReconcileObservation:
        return self._observation.reconcile_exact(contract)

    def unresolved_start(self, contract: ServiceLaunchContract):
        return self._observation.unresolved_start(contract)

    def start_exact(self, contract: ServiceLaunchContract) -> ServiceStartReport:
        return self._start.start_exact(contract)

    def stop_exact(self, contract: ServiceLaunchContract) -> ServiceSupervisorState:
        return self._stop.stop_exact(contract)

    def prepare_unexpected_exit(
        self,
        contract: ServiceLaunchContract,
        crash_adapter: ServiceCrashEvidenceAdapter,
    ) -> ServiceCrashReport:
        return self._crash.prepare_unexpected_exit(contract, crash_adapter)

    def commit_clean_exit(
        self,
        contract: ServiceLaunchContract,
        report: ServiceCrashReport,
    ) -> ServiceSupervisorState:
        return self._crash.commit_clean_exit(contract, report)

    def commit_handoff_transition(
        self,
        contract: ServiceLaunchContract,
        *,
        process: ServiceProcessIdentity,
        exit_class: ServiceExitClass,
        stdout_capture_ref: str,
        stderr_capture_ref: str,
        failure_id: str | None = None,
    ) -> ServiceSupervisorState:
        return self._crash.commit_handoff_transition(
            contract,
            process=process,
            exit_class=exit_class,
            stdout_capture_ref=stdout_capture_ref,
            stderr_capture_ref=stderr_capture_ref,
            failure_id=failure_id,
        )


__all__ = ["ExactServiceSupervisor"]
