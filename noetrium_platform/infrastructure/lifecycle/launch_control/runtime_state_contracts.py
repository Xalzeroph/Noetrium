from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuntimeTxnPhase(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    RECOVERY_REQUIRED = "recovery_required"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


@dataclass(frozen=True, slots=True)
class RuntimeControlState:
    control_id: str
    manifest_digest: str
    phase: RuntimeTxnPhase
    completed_actions: tuple[str, ...]
    current_action: str | None
    current_mutating: bool
    evidence_refs: tuple[str, ...]
    last_error_type: str | None
    last_error: str | None
    last_error_digest: str | None
    updated_at: float


__all__ = ["RuntimeControlState", "RuntimeTxnPhase"]
