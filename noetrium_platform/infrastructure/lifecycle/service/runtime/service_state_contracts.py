from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from dataclasses import dataclass
import time
import math

from .contracts import ServiceExitClass, ServicePhase


@dataclass(frozen=True, slots=True)
class ServiceSupervisorState:
    service_id: str
    contract_digest: str
    phase: ServicePhase
    attempt: int
    process: ServiceProcessIdentity | None
    ready_evidence_ref: str | None
    stdout_capture_ref: str | None
    stderr_capture_ref: str | None
    last_heartbeat_at: float | None
    last_failure_id: str | None
    last_exit_class: ServiceExitClass | None
    updated_at: float
    ready_at: float | None = None

    def __post_init__(self) -> None:
        if self.ready_at is not None and (
            not math.isfinite(float(self.ready_at)) or self.ready_at <= 0
        ):
            raise ValueError("service ready_at must be finite and positive")

    @classmethod
    def initial(cls, service_id: str, contract_digest: str) -> "ServiceSupervisorState":
        return cls(
            service_id,
            contract_digest,
            ServicePhase.NEW,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            time.time(),
        )


__all__ = ["ServiceSupervisorState"]
