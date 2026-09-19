from __future__ import annotations

from dataclasses import dataclass

from .ports import (
    ForensicCriticalWriteLanePort,
    ForensicEventWriteLanePort,
    ForensicIndexPort,
    ForensicLedgerPort,
    ForensicWriterLeasePort,
)


@dataclass(frozen=True, slots=True)
class ForensicRuntimeParts:
    """Provider-neutral resource bundle consumed by the forensic runtime."""

    failures: ForensicLedgerPort
    events: ForensicLedgerPort
    mutations: ForensicLedgerPort
    index: ForensicIndexPort
    event_lane: ForensicEventWriteLanePort | None
    failure_lane: ForensicCriticalWriteLanePort | None
    mutation_lane: ForensicCriticalWriteLanePort | None
    writer_lease: ForensicWriterLeasePort | None


__all__ = ["ForensicRuntimeParts"]
