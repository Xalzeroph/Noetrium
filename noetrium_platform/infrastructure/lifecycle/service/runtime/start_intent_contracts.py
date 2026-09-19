from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from dataclasses import dataclass
from enum import StrEnum

from .prepared_start import ServiceStartRecoveryHandle


class ServiceStartIntentPhase(StrEnum):
    PREPARED = "prepared"
    PROCESS_CONFIRMED = "process_confirmed"
    STATE_COMMITTED = "state_committed"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ServiceStartIntent:
    intent_id: str
    service_id: str
    contract_digest: str
    attempt: int
    phase: ServiceStartIntentPhase
    recovery_handle: ServiceStartRecoveryHandle | None
    process: ServiceProcessIdentity | None
    created_at: float
    updated_at: float


__all__ = ["ServiceStartIntent", "ServiceStartIntentPhase"]
