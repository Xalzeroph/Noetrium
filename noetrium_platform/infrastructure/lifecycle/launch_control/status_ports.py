from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel.errors import SafeExceptionDescriptor
from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat

from .runtime_state_contracts import RuntimeControlState


@dataclass(frozen=True, slots=True)
class RuntimeControlStatusObservation:
    state: RuntimeControlState | None
    history_errors: tuple[str, ...] = ()
    history_tail_error: SafeExceptionDescriptor | None = None
    evidence_refs: tuple[str, ...] = ()


class RuntimeControlStatusPort(Protocol):
    def observe(self) -> RuntimeControlStatusObservation: ...


@dataclass(frozen=True, slots=True)
class ServiceHeartbeatObservation:
    heartbeat: ServiceHeartbeat | None
    evidence_refs: tuple[str, ...] = ()


class ServiceHeartbeatStatusPort(Protocol):
    def observe(self, deployment_id: str) -> ServiceHeartbeatObservation: ...


__all__ = [
    "RuntimeControlStatusObservation",
    "RuntimeControlStatusPort",
    "ServiceHeartbeatObservation",
    "ServiceHeartbeatStatusPort",
]
