from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.unit import NoetriumUnit


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
    result_snapshot_json: str | None = None
    consumption_json: str | None = None
    consumption_digest: str | None = None


class EffectJournalWriteSession(AbstractContextManager["EffectJournalWriteSession"], Protocol):
    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None: ...
    def read_event_head(self, intent_id: str) -> NoetriumUnit | None: ...
    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]: ...
    def insert(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
    ) -> bool: ...
    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
        expected_event_digest: str,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool: ...
    def commit(self) -> None: ...


class EffectJournalPersistenceBackend(Protocol):
    durability: str
    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None: ...
    def read_event_head(self, intent_id: str) -> NoetriumUnit | None: ...
    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]: ...
    def scan_run(
        self,
        *,
        run_id: str,
    ) -> tuple[EncodedEffectIntentRecord, ...]: ...
    def scan_run_events(
        self,
        *,
        run_id: str,
    ) -> tuple[NoetriumUnit, ...]: ...
    def write_session(self) -> EffectJournalWriteSession: ...
    def close(self) -> None: ...


__all__ = [
    "EncodedEffectIntentRecord",
    "EffectJournalPersistenceBackend",
    "EffectJournalWriteSession",
]
