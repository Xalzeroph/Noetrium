from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from dataclasses import replace
import time

from .contracts import ServicePhase
from .service_state_contracts import ServiceSupervisorState
from .state_ports import ServiceStateStorePort


class ServiceStateTransitionWriter:
    """The sole helper for timestamped supervisor-state phase publication."""

    def __init__(self, store: ServiceStateStorePort) -> None:
        self.store = store

    def initialize(self, contract: ServiceLaunchContract) -> ServiceSupervisorState:
        state = ServiceSupervisorState.initial(contract.service_id, contract.digest())
        self.store.write(state)
        return state

    def persist(
        self,
        state: ServiceSupervisorState,
        phase: ServicePhase,
        **changes: object,
    ) -> ServiceSupervisorState:
        updated = replace(state, phase=phase, updated_at=time.time(), **changes)
        self.store.write(updated)
        return updated


__all__ = ["ServiceStateTransitionWriter"]
