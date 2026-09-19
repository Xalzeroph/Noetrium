from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from .contracts import ServicePhase
from .supervisor import ExactServiceSupervisor


class ExactServiceRuntimeEndpoint:
    """Cross-system semantic endpoint over one internal exact-service supervisor."""

    def __init__(self, supervisor: ExactServiceSupervisor) -> None:
        self._supervisor = supervisor

    def reconcile_exact(self, contract: ServiceLaunchContract) -> ServiceReconcileObservation:
        return self._supervisor.reconcile_exact(contract)

    def start_exact(self, contract: ServiceLaunchContract) -> ServiceStartOutcome:
        report = self._supervisor.start_exact(contract)
        state = report.state
        if (
            state.phase is not ServicePhase.RUNNING
            or state.process is None
            or not state.ready_evidence_ref
            or state.ready_at is None
        ):
            raise RuntimeError("service start completed without exact READY state")
        return ServiceStartOutcome(
            contract_digest=state.contract_digest,
            process=state.process,
            ready_evidence_ref=state.ready_evidence_ref,
            ready_at=state.ready_at,
            evidence_refs=tuple(report.evidence_refs),
        )

    def verify_ready_exact(self, contract: ServiceLaunchContract) -> ServiceReadyObservation:
        state = self._supervisor.observe_state(contract)
        if state is None:
            raise RuntimeError("service has no supervisor state")
        if (
            state.phase is not ServicePhase.RUNNING
            or state.process is None
            or not state.ready_evidence_ref
            or state.ready_at is None
        ):
            raise RuntimeError("service is not exactly ready")
        reconciled = self._supervisor.reconcile_exact(contract)
        if reconciled.process is None or reconciled.process != state.process:
            raise RuntimeError("service exact process is not live")
        return ServiceReadyObservation(
            contract_digest=state.contract_digest,
            process=state.process,
            ready_evidence_ref=state.ready_evidence_ref,
            ready_at=state.ready_at,
            evidence_refs=tuple(reconciled.evidence_refs),
        )

    def stop_exact(self, contract: ServiceLaunchContract) -> ServiceStopOutcome:
        state = self._supervisor.observe_state(contract)
        if state is None:
            return ServiceStopOutcome(contract_digest=contract.digest(), stopped=True, evidence_refs=())
        stopped = self._supervisor.stop_exact(contract)
        return ServiceStopOutcome(
            contract_digest=stopped.contract_digest,
            stopped=stopped.process is None,
            evidence_refs=(),
        )


__all__ = ["ExactServiceRuntimeEndpoint"]
