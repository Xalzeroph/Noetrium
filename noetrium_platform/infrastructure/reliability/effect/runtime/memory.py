from __future__ import annotations

from threading import RLock

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentConflict,
    EffectIntentJournal,
    EffectIntentPhase,
    EffectIntentPrepareResult,
    EffectIntentRecord,
    consumed_transition,
    effect_transition,
    not_applied_transition,
    prepare_transition,
)
from noetrium_platform.foundation.kernel.kernel import EffectReceipt


class InMemoryEffectIntentJournal(EffectIntentJournal):
    """Process-local storage adapter over the single effect transition authority."""

    durability = "process_local"

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, EffectIntentRecord] = {}
        self._unresolved_by_scope: dict[tuple[str, str | None], set[str]] = {}

    def prepare(self, intent: EffectIntent) -> EffectIntentPrepareResult:
        with self._lock:
            result = prepare_transition(self._records.get(intent.intent_id), intent)
            if result.created:
                self._records[intent.intent_id] = result.record
                self._unresolved_by_scope.setdefault(
                    (intent.run_id, intent.lifetime_id), set()
                ).add(intent.intent_id)
            return result

    def load(self, intent_id: str) -> EffectIntentRecord | None:
        with self._lock:
            return self._records.get(intent_id)

    def _current(self, intent_id: str) -> EffectIntentRecord:
        current = self._records.get(intent_id)
        if current is None:
            raise EffectIntentConflict(f"unknown effect intent: {intent_id}")
        return current

    def _store(self, current: EffectIntentRecord, desired: EffectIntentRecord) -> EffectIntentRecord:
        if desired is not current:
            self._records[current.intent.intent_id] = desired
            if desired.phase.terminal:
                scope = (current.intent.run_id, current.intent.lifetime_id)
                intent_ids = self._unresolved_by_scope.get(scope)
                if intent_ids is not None:
                    intent_ids.discard(current.intent.intent_id)
                    if not intent_ids:
                        self._unresolved_by_scope.pop(scope, None)
        return desired

    def record_result(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt | None
    ) -> EffectIntentRecord:
        with self._lock:
            current = self._current(intent_id)
            return self._store(current, effect_transition(
                current,
                request_digest=request_digest,
                phase=EffectIntentPhase.RESULT_RECORDED,
                effect=effect,
            ))

    def record_reconciled(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt
    ) -> EffectIntentRecord:
        with self._lock:
            current = self._current(intent_id)
            return self._store(current, effect_transition(
                current,
                request_digest=request_digest,
                phase=EffectIntentPhase.RECONCILED,
                effect=effect,
            ))

    def record_consumed(
        self, intent_id: str, *, request_digest: str, consumption: EffectCompletionEvidence
    ) -> EffectIntentRecord:
        with self._lock:
            current = self._current(intent_id)
            return self._store(current, consumed_transition(
                current,
                request_digest=request_digest,
                consumption=consumption,
            ))

    def record_not_applied(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt
    ) -> EffectIntentRecord:
        with self._lock:
            current = self._current(intent_id)
            return self._store(current, not_applied_transition(
                current,
                request_digest=request_digest,
                effect=effect,
            ))

    def unresolved_for_scope(
        self, *, run_id: str, lifetime_id: str | None, exclude_intent_id: str | None = None
    ) -> tuple[EffectIntentRecord, ...]:
        with self._lock:
            intent_ids = self._unresolved_by_scope.get((run_id, lifetime_id), ())
            matched = [
                self._records[intent_id]
                for intent_id in intent_ids
                if intent_id != exclude_intent_id
            ]
        return tuple(sorted(matched, key=lambda row: row.intent.intent_id))


__all__ = ["InMemoryEffectIntentJournal"]
