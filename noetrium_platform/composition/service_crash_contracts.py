from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceExitClass


class CrashHandoffPhase(StrEnum):
    PREPARED = "prepared"
    FAILURE_DURABLE = "failure_durable"
    STATE_COMMITTED = "state_committed"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class DurableCrashHandoff:
    schema_version: int
    handoff_id: str
    service_id: str
    contract_digest: str
    process: ServiceProcessIdentity
    exit_class: ServiceExitClass
    stdout_capture_ref: str
    stderr_capture_ref: str
    failure: FailureEnvelope
    phase: CrashHandoffPhase
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class CrashHandoffReport:
    handoff: DurableCrashHandoff
    failure_appended: bool


__all__ = ["CrashHandoffPhase", "CrashHandoffReport", "DurableCrashHandoff"]
