from __future__ import annotations

from contextlib import AbstractContextManager
from threading import RLock

from noetrium_platform.foundation.kernel.event import is_event_unit
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord
from .persistent import EffectIntentJournalRuntime


class MemoryEffectJournalWriteSession(
    AbstractContextManager["MemoryEffectJournalWriteSession"]
):
    """Atomic process-local projection + append-only Event transaction."""

    def __init__(self, backend: "MemoryEffectJournalBackend") -> None:
        self._backend = backend
        self._committed = False
        self._pending_record: EncodedEffectIntentRecord | None = None
        self._pending_events: list[NoetriumUnit] = []
        backend._lock.acquire()

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        if (
            self._pending_record is not None
            and self._pending_record.intent_id == intent_id
        ):
            return self._pending_record
        return self._backend._records.get(intent_id)

    def read_event_head(self, intent_id: str) -> NoetriumUnit | None:
        if (
            self._pending_record is not None
            and self._pending_record.intent_id == intent_id
            and self._pending_events
        ):
            return self._pending_events[-1]
        digest = self._backend._heads.get(intent_id)
        if digest is None:
            return None
        event = self._backend._events.get(digest)
        if event is None:
            raise RuntimeError(
                "memory effect projection event head is missing: " + intent_id
            )
        return event

    def scan_scope_phases(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        phases: tuple[str, ...],
        exclude_intent_id: str | None = None,
    ) -> tuple[EncodedEffectIntentRecord, ...]:
        allowed = set(phases)
        rows = dict(self._backend._records)
        if self._pending_record is not None:
            rows[self._pending_record.intent_id] = self._pending_record
        return tuple(
            row
            for intent_id, row in sorted(rows.items())
            if row.run_id == run_id
            and row.lifetime_id == lifetime_id
            and row.phase in allowed
            and intent_id != exclude_intent_id
        )

    def insert(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
    ) -> bool:
        if not is_event_unit(event):
            raise TypeError("effect journal append requires system.event Unit")
        if value.intent_id in self._backend._records:
            return False
        if (
            event.unit_digest in self._backend._events
            or any(row.unit_digest == event.unit_digest for row in self._pending_events)
        ):
            return False
        self._pending_record = value
        self._pending_events.append(event)
        return True

    def update(
        self,
        value: EncodedEffectIntentRecord,
        *,
        event: NoetriumUnit,
        expected_event_digest: str,
        expected_phase: str,
        expected_effect_digest: str | None,
    ) -> bool:
        if not is_event_unit(event):
            raise TypeError("effect journal append requires system.event Unit")
        current = (
            self._pending_record
            if self._pending_record is not None
            and self._pending_record.intent_id == value.intent_id
            else self._backend._records.get(value.intent_id)
        )
        if current is None:
            return False
        current_head = (
            self._pending_events[-1].unit_digest
            if self._pending_record is not None
            and self._pending_record.intent_id == value.intent_id
            and self._pending_events
            else self._backend._heads.get(value.intent_id)
        )
        if (
            current.phase != expected_phase
            or current.effect_digest != expected_effect_digest
            or current_head != expected_event_digest
            or event.unit_digest in self._backend._events
            or any(row.unit_digest == event.unit_digest for row in self._pending_events)
        ):
            return False
        self._pending_record = value
        self._pending_events.append(event)
        return True

    def commit(self) -> None:
        if self._pending_record is not None:
            if not self._pending_events:
                raise RuntimeError("effect projection mutation lacks Event Unit")
            value = self._pending_record
            for event in self._pending_events:
                self._backend._events[event.unit_digest] = event
                self._backend._event_run[event.unit_digest] = value.run_id
            self._backend._heads[value.intent_id] = self._pending_events[-1].unit_digest
            self._backend._records[value.intent_id] = value
        self._committed = True

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc, tb
        self._pending_record = None
        self._pending_events.clear()
        self._backend._lock.release()
        return False


class MemoryEffectJournalBackend(EffectJournalPersistenceBackend):
    """Process-local storage implementing the same Event-sourced semantics."""

    durability = "process_local"

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, EncodedEffectIntentRecord] = {}
        self._events: dict[str, NoetriumUnit] = {}
        self._event_run: dict[str, str] = {}
        self._heads: dict[str, str] = {}

    def read(self, intent_id: str) -> EncodedEffectIntentRecord | None:
        with self._lock:
            return self._records.get(intent_id)

    def read_event_head(self, intent_id: str) -> NoetriumUnit | None:
        with self._lock:
            digest = self._heads.get(intent_id)
            if digest is None:
                return None
            event = self._events.get(digest)
            if event is None:
                raise RuntimeError(
                    "memory effect projection event head is missing: " + intent_id
                )
            return event

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

    def scan_run_events(
        self,
        *,
        run_id: str,
    ) -> tuple[NoetriumUnit, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect event run_id must be non-empty text")
        with self._lock:
            return tuple(
                self._events[digest]
                for digest in sorted(self._events)
                if self._event_run[digest] == run_id
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
