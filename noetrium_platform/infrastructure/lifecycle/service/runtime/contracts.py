from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import math

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity


class ServiceExitClass(IntEnum):
    CLEAN = 0
    SOFTWARE = 70
    IO_ERROR = 74
    TEMPORARY = 75
    CONFIGURATION = 78


class ServicePhase(StrEnum):
    NEW = "new"
    VERIFY_CONTRACT = "verify_contract"
    RECONCILE_PRIOR = "reconcile_prior"
    START_CHILD = "start_child"
    WAIT_READY = "wait_ready"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPING = "stopping"
    EXITED = "exited"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class ServiceReadinessProofMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ServiceReadyEvidence:
    contract_digest: str
    process: ServiceProcessIdentity
    readiness_ref: str
    stdout_capture_ref: str
    stderr_capture_ref: str
    ready_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.contract_digest, str) or len(self.contract_digest) != 64 or any(c not in "0123456789abcdef" for c in self.contract_digest):
            raise ValueError("service readiness contract digest must be canonical SHA-256")
        if not isinstance(self.process, ServiceProcessIdentity):
            raise ValueError("service readiness process identity must be typed")
        refs = (self.readiness_ref, self.stdout_capture_ref, self.stderr_capture_ref)
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValueError("service readiness evidence references must be non-empty strings")
        if isinstance(self.ready_at, bool) or not isinstance(self.ready_at, (int, float)) or not math.isfinite(float(self.ready_at)) or self.ready_at <= 0:
            raise ValueError("service readiness observation time must be finite and positive")


__all__ = ["ServiceExitClass", "ServicePhase", "ServiceReadyEvidence", "ServiceReadinessProofMismatch"]
