from __future__ import annotations

from contextlib import AbstractContextManager
from threading import RLock

from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord
from .persistent import EffectIntentJournalRuntime

class MemoryEffectJournalWriteSession(AbstractContextManager["MemoryEffectJournalWriteSession"]):
    def __init__(self, backend: "MemoryEffectJournalBackend") -> None:
        self._backend = backend
        self._committed = False
        backend._lock.acquire()

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        return self._backend._records.get(intent_id)

    def insert(self, value: EncodedEffectIntentRecord) -> bool:
        if value.intent_id in self._backend._records:
            return False
        self._backend._records[value.intent_id] = value
        return True

    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool:
        current = self._backend._records.get(value.intent_id)
        if current is None:
            return False
        if current.phase != expected_phase or current.effect_digest != expected_effect_digest:
            return False
        self._backend._records[value.intent_id] = value
        return True

    def commit(self) -> None:
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc, tb
        self._backend._lock.release()
        return False


class MemoryEffectJournalBackend(EffectJournalPersistenceBackend):
    """Process-local backend for the single EffectIntentJournalRuntime."""

    durability = "process_local"

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, EncodedEffectIntentRecord] = {}

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        with self._lock:
            return self._records.get(intent_id)

    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        allowed = set(phases)
        with self._lock:
            return tuple(
                row
                for intent_id, row in sorted(self._records.items())
                if row.run_id == run_id
                and row.lifetime_id == lifetime_id
                and row.phase in allowed
                and intent_id != exclude_intent_id
            )
    def scan_run(
        self,
        *,
        run_id: str,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect journal run_id must be non-empty text")
        with self._lock:
            return tuple(
                row
                for _intent_id, row in sorted(self._records.items())
                if row.run_id == run_id
            )

    def write_session(self) -> MemoryEffectJournalWriteSession:
        return MemoryEffectJournalWriteSession(self)

    def close(self) -> None:
        return None


def memory_effect_intent_journal() -> EffectIntentJournalRuntime:
    return EffectIntentJournalRuntime(MemoryEffectJournalBackend())


__all__ = [
    "MemoryEffectJournalBackend",
    "MemoryEffectJournalWriteSession",
    "memory_effect_intent_journal",
]
