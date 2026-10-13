from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from dataclasses import dataclass
from typing import Protocol

from .contracts import ServiceReadyEvidence
from .service_state_contracts import ServiceSupervisorState


class ServiceProcessAdapter(Protocol):
    def reconcile(
        self,
        state: ServiceSupervisorState,
        contract: ServiceLaunchContract,
    ) -> tuple[ServiceProcessIdentity | None, tuple[str, ...]]: ...

    def start(
        self,
        contract: ServiceLaunchContract,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]: ...

    def wait_ready(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> ServiceReadyEvidence: ...

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ServiceStartReport:
    state: ServiceSupervisorState
    evidence_refs: tuple[str, ...]


__all__ = ["ServiceProcessAdapter", "ServiceStartReport"]
