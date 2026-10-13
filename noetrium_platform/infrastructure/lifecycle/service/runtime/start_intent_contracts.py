from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)

from .prepared_start import ServiceStartRecoveryHandle


class ServiceStartIntentPhase(StrEnum):
    PREPARED = "prepared"
    PROCESS_CONFIRMED = "process_confirmed"
    STATE_COMMITTED = "state_committed"
    COMPLETE = "complete"
    ABORTED = "aborted"

    @property
    def terminal(self) -> bool:
        return self in {
            ServiceStartIntentPhase.COMPLETE,
            ServiceStartIntentPhase.ABORTED,
        }


@dataclass(frozen=True, slots=True)
class ServiceStartIntent:
    """Crash-durable start intent carrying its complete immutable contract."""

    intent_id: str
    contract: ServiceLaunchContract
    attempt: int
    phase: ServiceStartIntentPhase
    recovery_handle: ServiceStartRecoveryHandle | None
    process: ServiceProcessIdentity | None
    created_at: float
    updated_at: float

    def __post_init__(self) -> None:
        if type(self.intent_id) is not str or not self.intent_id:
            raise ValueError("service-start intent id is required")
        if not isinstance(self.contract, ServiceLaunchContract):
            raise TypeError("service-start intent requires frozen launch contract")
        if type(self.attempt) is not int or self.attempt <= 0:
            raise ValueError("service-start intent attempt must be positive")
        if not isinstance(self.phase, ServiceStartIntentPhase):
            raise TypeError("service-start intent phase must be typed")
        if (
            self.phase
            in {
                ServiceStartIntentPhase.PROCESS_CONFIRMED,
                ServiceStartIntentPhase.STATE_COMMITTED,
                ServiceStartIntentPhase.COMPLETE,
            }
            and self.process is None
        ):
            raise ValueError(
                "post-prepare service-start intent requires process identity"
            )

    @property
    def service_id(self) -> str:
        return self.contract.service_id

    @property
    def contract_digest(self) -> str:
        return self.contract.digest()


__all__ = ["ServiceStartIntent", "ServiceStartIntentPhase"]
