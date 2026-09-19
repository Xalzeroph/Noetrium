from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .runtime_state_contracts import RuntimeControlState


RUNTIME_HISTORY_ROW_SCHEMA_VERSION = 2


class RuntimeHistoryProjectionKind(StrEnum):
    STATE_WRITE = "state_write"
    AUTHORITATIVE_RECONCILE = "authoritative_reconcile"


class RuntimeHistoryIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeHistoryEntry:
    sequence: int
    timestamp: float
    state: RuntimeControlState
    state_sha256: str
    projection_kind: RuntimeHistoryProjectionKind
    previous_sha256: str | None
    row_sha256: str


__all__ = [
    "RUNTIME_HISTORY_ROW_SCHEMA_VERSION",
    "RuntimeHistoryEntry",
    "RuntimeHistoryIntegrityError",
    "RuntimeHistoryProjectionKind",
]
