from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EncodedEffectIntentRecord:
    """Storage-neutral encoded row for the generic effect WAL.

    Physical backends may retain historical table/column names; those names are not
    part of the runtime-domain contract.
    """

    intent_id: str
    intent_json: str
    intent_digest: str
    request_digest: str
    run_id: str
    lifetime_id: str | None
    phase: str
    effect_json: str | None
    effect_digest: str | None
    consumption_json: str | None = None
    consumption_digest: str | None = None


class EffectJournalWriteSession(AbstractContextManager["EffectJournalWriteSession"], Protocol):
    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None: ...
    def insert(self, value: EncodedEffectIntentRecord) -> bool: ...
    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool: ...
    def commit(self) -> None: ...


class EffectJournalPersistenceBackend(Protocol):
    durability: str
    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None: ...
    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]: ...
    def write_session(self) -> EffectJournalWriteSession: ...


__all__ = [
    "EncodedEffectIntentRecord",
    "EffectJournalPersistenceBackend",
    "EffectJournalWriteSession",
]
