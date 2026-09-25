from __future__ import annotations

from typing import Protocol

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

from .generic_codec import EffectJournalDocumentCodec
from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord


class EffectJournalCodec(Protocol):
    def encode_record(self, record: EffectIntentRecord) -> EncodedEffectIntentRecord: ...
    def decode_record(self, encoded: EncodedEffectIntentRecord) -> EffectIntentRecord: ...
    def completion_digest(self, consumption: EffectCompletionEvidence | None) -> str | None: ...


class PersistentEffectIntentJournal(EffectIntentJournal):
    """Persistent CAS adapter over the single effect-domain transition authority."""

    def __init__(
        self,
        backend: EffectJournalPersistenceBackend,
        *,
        codec: EffectJournalCodec | None = None,
    ) -> None:
        self.backend = backend
        self.codec: EffectJournalCodec = codec or EffectJournalDocumentCodec()
        self.durability = backend.durability

    def load(self, intent_id: str) -> EffectIntentRecord | None:
        row = self.backend.read(intent_id)
        return self.codec.decode_record(row) if row is not None else None

    @staticmethod
    def _unknown(intent_id: str) -> EffectIntentConflict:
        return EffectIntentConflict(f"unknown effect intent: {intent_id}")

    def prepare(self, intent: EffectIntent) -> EffectIntentPrepareResult:
        with self.backend.write_session() as tx:
            current_encoded = tx.read(intent.intent_id)
            current = self.codec.decode_record(current_encoded) if current_encoded is not None else None
            result = prepare_transition(current, intent)
            if result.created and not tx.insert(self.codec.encode_record(result.record)):
                raise EffectIntentConflict(f"effect intent concurrent insert conflict: {intent.intent_id}")
            tx.commit()
            return result

    def _transition(self, intent_id: str, transition) -> EffectIntentRecord:
        with self.backend.write_session() as tx:
            encoded = tx.read(intent_id)
            if encoded is None:
                raise self._unknown(intent_id)
            current = self.codec.decode_record(encoded)
            desired = transition(current)
            if desired is not current:
                if not tx.update(
                    self.codec.encode_record(desired),
                    expected_phase=current.phase.value,
                    expected_effect_digest=current.effect_digest,
                ):
                    raise EffectIntentConflict(f"effect intent concurrent transition conflict: {intent_id}")
            tx.commit()
            return desired

    def record_result(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt | None
    ) -> EffectIntentRecord:
        return self._transition(intent_id, lambda current: effect_transition(
            current,
            request_digest=request_digest,
            phase=EffectIntentPhase.RESULT_RECORDED,
            effect=effect,
        ))

    def record_reconciled(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt
    ) -> EffectIntentRecord:
        return self._transition(intent_id, lambda current: effect_transition(
            current,
            request_digest=request_digest,
            phase=EffectIntentPhase.RECONCILED,
            effect=effect,
        ))

    def record_consumed(
        self, intent_id: str, *, request_digest: str, consumption: EffectCompletionEvidence
    ) -> EffectIntentRecord:
        return self._transition(intent_id, lambda current: consumed_transition(
            current,
            request_digest=request_digest,
            consumption=consumption,
        ))

    def record_not_applied(
        self, intent_id: str, *, request_digest: str, effect: EffectReceipt
    ) -> EffectIntentRecord:
        return self._transition(intent_id, lambda current: not_applied_transition(
            current,
            request_digest=request_digest,
            effect=effect,
        ))

    def unresolved_for_scope(
        self, *, run_id: str, lifetime_id: str | None, exclude_intent_id: str | None = None
    ) -> tuple[EffectIntentRecord, ...]:
        phases = tuple(phase.value for phase in EffectIntentPhase if not phase.terminal)
        encoded = self.backend.scan_scope_phases(
            run_id=run_id,
            lifetime_id=lifetime_id,
            phases=phases,
            exclude_intent_id=exclude_intent_id,
        )
        return tuple(self.codec.decode_record(row) for row in encoded)


__all__ = ["EffectJournalCodec", "PersistentEffectIntentJournal"]
