from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from typing import Protocol, runtime_checkable



@dataclass(frozen=True, slots=True)
class ServiceStartRecoveryHandle:
    provider_schema: str
    payload_sha256: str
    opaque_payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.provider_schema:
            raise ValueError("service-start recovery handle schema required")
        actual = hashlib.sha256(self.opaque_payload).hexdigest()
        if self.payload_sha256 != actual:
            raise ValueError("service-start recovery handle payload checksum mismatch")

    @classmethod
    def from_payload(cls, provider_schema: str, payload: bytes) -> "ServiceStartRecoveryHandle":
        return cls(provider_schema, hashlib.sha256(payload).hexdigest(), payload)


class PreparedServiceStartStatus(StrEnum):
    PROCESS_CONFIRMED = "process_confirmed"
    NOT_STARTED = "not_started"
    UNKNOWN = "unknown"
    DRIFT = "drift"


@dataclass(frozen=True, slots=True)
class PreparedServiceStartReconcileResult:
    status: PreparedServiceStartStatus
    process: ServiceProcessIdentity | None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is PreparedServiceStartStatus.PROCESS_CONFIRMED and self.process is None:
            raise ValueError("confirmed prepared start requires process identity")
        if self.status is not PreparedServiceStartStatus.PROCESS_CONFIRMED and self.process is not None:
            raise ValueError("non-confirmed prepared start cannot carry process identity")


@runtime_checkable
class CrashDurableServiceStartAdapter(Protocol):
    start_recovery_durability: str

    def prepare_start_recovery(
        self,
        contract: ServiceLaunchContract,
        *,
        intent_id: str,
        attempt: int,
    ) -> ServiceStartRecoveryHandle: ...

    def start_prepared(
        self,
        contract: ServiceLaunchContract,
        handle: ServiceStartRecoveryHandle,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]: ...

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult: ...


def crash_durable_start_adapter(value: object) -> CrashDurableServiceStartAdapter | None:
    if not isinstance(value, CrashDurableServiceStartAdapter):
        return None
    if value.start_recovery_durability != "crash_durable":
        return None
    return value


__all__ = [
    "CrashDurableServiceStartAdapter",
    "PreparedServiceStartReconcileResult",
    "PreparedServiceStartStatus",
    "ServiceStartRecoveryHandle",
    "crash_durable_start_adapter",
]
