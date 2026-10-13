from __future__ import annotations

from .start_effect_journal import ServiceStartEffectJournal
from .state_ports import ServiceStateStorePort
from .status_ports import ServiceOperationalStatusObservation


class ServiceOperationalStatusReader:
    """Read-only join of service projection + unresolved Effect projections."""

    def __init__(
        self,
        state: ServiceStateStorePort,
        start_effects: ServiceStartEffectJournal,
    ) -> None:
        self.state = state
        self.start_effects = start_effects

    def observe(self) -> ServiceOperationalStatusObservation:
        if not self.state.exists():
            return ServiceOperationalStatusObservation(None)
        state = self.state.read()
        intents = self.start_effects.unresolved_scope(
            state.service_id,
            state.contract_digest,
        )
        refs = [self.state.reference()]
        refs.extend(f"service-start-effect:{intent.intent_id}" for intent in intents)
        return ServiceOperationalStatusObservation(state, tuple(intents), tuple(refs))


__all__ = ["ServiceOperationalStatusReader"]
