from __future__ import annotations

from .start_intent_ports import ServiceStartIntentReadPort
from .state_ports import ServiceStateStorePort
from .status_ports import ServiceOperationalStatusObservation


class ServiceOperationalStatusReader:
    """Read-only join of service state + start-intent projection for operator status."""

    def __init__(
        self,
        state: ServiceStateStorePort,
        intents: ServiceStartIntentReadPort,
    ) -> None:
        self.state = state
        self.intents = intents

    def observe(self) -> ServiceOperationalStatusObservation:
        if not self.state.exists():
            return ServiceOperationalStatusObservation(None)
        state = self.state.read()
        intents = self.intents.unresolved(state.service_id, state.contract_digest)
        refs = [self.state.reference()]
        refs.extend(f"service-start-intent:{intent.intent_id}" for intent in intents)
        return ServiceOperationalStatusObservation(state, tuple(intents), tuple(refs))


__all__ = ["ServiceOperationalStatusReader"]
