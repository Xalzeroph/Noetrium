from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceContractDrift,
    ServiceLaunchContract,
    ServiceReconcileObservation,
)
from .start_journal import ServiceStartJournal
from .state_ports import ServiceStateStorePort
from .supervision_contracts import ServiceProcessAdapter
from .service_state_contracts import ServiceSupervisorState


class ServiceObservationCoordinator:
    """Read/reconcile authority for one exact service; performs no state mutation."""

    def __init__(
        self,
        store: ServiceStateStorePort,
        adapter: ServiceProcessAdapter,
        start_journal: ServiceStartJournal,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._start_journal = start_journal

    def observe_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState | None:
        if not self._store.exists():
            return None
        state = self._store.read()
        if state.contract_digest != contract.digest():
            raise ServiceContractDrift("persisted service state belongs to a different launch contract")
        return state

    def reconcile_exact(self, contract: ServiceLaunchContract) -> ServiceReconcileObservation:
        state = self.observe_state(contract)
        if state is None:
            return ServiceReconcileObservation(False, None, ())
        process, refs = self._adapter.reconcile(state, contract)
        return ServiceReconcileObservation(True, process, tuple(refs))

    def unresolved_start(self, contract: ServiceLaunchContract):
        return self._start_journal.unresolved(contract)


__all__ = ["ServiceObservationCoordinator"]
