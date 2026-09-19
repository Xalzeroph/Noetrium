from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .service_state_contracts import ServiceSupervisorState
from .start_intent_contracts import ServiceStartIntent


@dataclass(frozen=True, slots=True)
class ServiceOperationalStatusObservation:
    state: ServiceSupervisorState | None
    unresolved_start_intents: tuple[ServiceStartIntent, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class ServiceOperationalStatusPort(Protocol):
    def observe(self) -> ServiceOperationalStatusObservation: ...


__all__ = ["ServiceOperationalStatusObservation", "ServiceOperationalStatusPort"]
