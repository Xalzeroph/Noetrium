from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IncidentPattern:
    fingerprint: str
    family_fingerprint: str
    count: int
    family_count: int
    first_seen: float
    last_seen: float
    example_failure_ids: tuple[str, ...]
    family_example_failure_ids: tuple[str, ...]
    signature: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IncidentProjectionSync:
    source_rows: int
    source_tail_hash: str
    added_failures: int
    rebuilt: bool


class IncidentProjectionPort(Protocol):
    """Disposable recurrence projection; source ledger/backend remains opaque to diagnostics."""

    def synchronize(self) -> IncidentProjectionSync: ...
    def get(self, fingerprint: str) -> IncidentPattern | None: ...


__all__ = ["IncidentPattern", "IncidentProjectionPort", "IncidentProjectionSync"]
