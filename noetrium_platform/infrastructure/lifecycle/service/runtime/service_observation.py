from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceContractDrift,
    ServiceLaunchContract,
    ServiceReconcileObservation,
)
from .start_effect_journal import ServiceStartEffectJournal
from .state_ports import ServiceStateStorePort
from .supervision_contracts import ServiceProcessAdapter
from .service_state_contracts import ServiceSupervisorState


class ServiceObservationCoordinator:
    """Read/reconcile authority for one exact service; performs no state mutation."""

    def __init__(
        self,
        store: ServiceStateStorePort,
        adapter: ServiceProcessAdapter,
        start_effects: ServiceStartEffectJournal,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._start_effects = start_effects

    def observe_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState | None:
        if not self._store.exists():
            return None
        state = self._store.read()
        if state.contract_digest != contract.digest():
            raise ServiceContractDrift("persisted service state belongs to a different launch contract")
        return state

    def reconcile_exact(self, contract: ServiceLaunchContract) -> ServiceReconcileObservation:
        """Observe every exact process ever confirmed for this contract.

        Supervisor state is a disposable projection and therefore cannot prove
        physical absence.  The causal start-Effect journal retains exact process
        identities; reconcile each of those identities against the physical
        backend before reporting quiescence.
        """
        state = self.observe_state(contract)
        candidates = []
        if state is not None and state.process is not None:
            candidates.append(state.process)
        for intent in self._start_effects.records_for_contract(contract):
            if intent.process is not None and intent.process not in candidates:
                candidates.append(intent.process)

        refs: list[str] = []
        live = []
        for candidate in candidates:
            seed = (
                state
                if state is not None and state.process == candidate
                else replace(
                    ServiceSupervisorState.initial(
                        contract.service_id,
                        contract.digest(),
                    ),
                    process=candidate,
                )
            )
            observed, evidence = self._adapter.reconcile(seed, contract)
            refs.extend(evidence)
            if observed is not None and observed not in live:
                live.append(observed)

        if len(live) > 1:
            from .process_contracts import ServiceProcessDrift
            raise ServiceProcessDrift(
                "multiple physical process generations remain live for one exact service contract"
            )
        return ServiceReconcileObservation(
            state is not None,
            None if not live else live[0],
            tuple(dict.fromkeys(refs)),
        )

    def unresolved_start(self, contract: ServiceLaunchContract):
        return self._start_effects.unresolved(contract)


__all__ = ["ServiceObservationCoordinator"]
