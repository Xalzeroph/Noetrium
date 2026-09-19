from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceContractDrift
from .service_state_contracts import ServiceSupervisorState
from .start_flow_common import ServiceReadinessCommitter
from .start_journal import ServiceStartJournal
from .start_new_flow import NewServiceStartFlow
from .start_recovery_flow import PreparedServiceStartRecoveryFlow
from .start_resume import ServiceStartRecoveryRequired, decide_service_start_resume
from .state_ports import ServiceStateStorePort
from .state_transition import ServiceStateTransitionWriter
from .supervision_contracts import ServiceProcessAdapter, ServiceStartReport


class ServiceStartCoordinator:
    """Choose normal or durable-recovery start flow for one frozen launch contract."""

    def __init__(
        self,
        store: ServiceStateStorePort,
        adapter: ServiceProcessAdapter,
        journal: ServiceStartJournal,
    ) -> None:
        self._store = store
        self._journal = journal
        transitions = ServiceStateTransitionWriter(store)
        self._transitions = transitions
        readiness = ServiceReadinessCommitter(adapter, transitions)
        self._new_flow = NewServiceStartFlow(adapter, transitions, self._journal, readiness)
        self._recovery_flow = PreparedServiceStartRecoveryFlow(
            adapter,
            transitions,
            self._journal,
            readiness,
        )

    def _load_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState:
        digest = contract.digest()
        if self._store.exists():
            state = self._store.read()
            if state.contract_digest != digest:
                raise ServiceContractDrift(
                    "existing service state belongs to a different immutable launch contract"
                )
            return state
        return self._transitions.initialize(contract)

    def start_exact(self, contract: ServiceLaunchContract) -> ServiceStartReport:
        state = self._load_state(contract)
        unresolved = self._journal.unresolved(contract)
        if unresolved is not None:
            return self._recovery_flow.recover(contract, state, unresolved)

        decision = decide_service_start_resume(state)
        if decision.blocked:
            raise ServiceStartRecoveryRequired(state, decision)
        return self._new_flow.execute(contract, state)


__all__ = ["ServiceStartCoordinator"]
