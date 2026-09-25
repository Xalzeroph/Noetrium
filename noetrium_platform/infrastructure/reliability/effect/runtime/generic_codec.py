from __future__ import annotations

import base64
import json

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentPhase,
    EffectIntentRecord,
    EffectJournalIntegrityError,
    PreparedEffectHandle,
    effect_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, canonical_digest
from .persistence import EncodedEffectIntentRecord


class EffectJournalDocumentCodec:
    """Provider-agnostic durable document codec for generic effect intents."""

    DOCUMENT_SCHEMA = "effect-intent.v1"

    @staticmethod
    def _require_index_match(
        intent_id: str, field: str, observed: object, authoritative: object
    ) -> None:
        if observed != authoritative:
            raise EffectJournalIntegrityError(
                f"effect journal {field} index mismatch: {intent_id}"
            )

    @staticmethod
    def _handle_payload(handle: PreparedEffectHandle | None) -> dict[str, object] | None:
        if handle is None:
            return None
        return {
            "request_id": handle.request_id,
            "request_digest": handle.request_digest,
            "provider_schema": handle.provider_schema,
            "opaque_payload_b64": base64.b64encode(handle.opaque_payload).decode("ascii"),
            "payload_sha256": handle.payload_sha256,
            "provider_instance_id": handle.provider_instance_id,
        }

    @staticmethod
    def _decode_handle(row: object) -> PreparedEffectHandle | None:
        if row is None:
            return None
        if not isinstance(row, dict):
            raise ValueError("invalid prepared effect handle document")
        return PreparedEffectHandle(
            str(row["request_id"]),
            str(row["request_digest"]),
            str(row["provider_schema"]),
            base64.b64decode(str(row["opaque_payload_b64"]).encode("ascii")),
            str(row["payload_sha256"]),
            None if row.get("provider_instance_id") is None else str(row["provider_instance_id"]),
        )

    def encode_intent(self, intent: EffectIntent) -> tuple[str, str]:
        payload = {
            "document_schema": self.DOCUMENT_SCHEMA,
            "intent_id": intent.intent_id,
            "request_id": intent.request_id,
            "operation_id": intent.operation_id,
            "request_digest": intent.request_digest,
            "provider_component_digest": intent.provider_component_digest,
            "run_id": intent.run_id,
            "trace_id": intent.trace_id,
            "study_id": intent.study_id,
            "lifetime_id": intent.lifetime_id,
            "task_id": intent.task_id,
            "decision_cycle_id": intent.decision_cycle_id,
            "checkpoint_id": intent.checkpoint_id,
            "source_generation": intent.source_generation,
            "recovery_handle": self._handle_payload(intent.recovery_handle),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")), canonical_digest(payload)

    def decode_intent(self, text: str) -> EffectIntent:
        row = json.loads(text)
        if row.get("document_schema") != self.DOCUMENT_SCHEMA:
            raise ValueError(f"unsupported effect intent document schema: {row.get('document_schema')}")
        return EffectIntent(
            row["intent_id"], row["request_id"], row["operation_id"], row["request_digest"],
            row["provider_component_digest"], row["run_id"], row["trace_id"], row.get("study_id"),
            row.get("lifetime_id"), row.get("task_id"), row.get("decision_cycle_id"),
            row.get("checkpoint_id"), row.get("source_generation"), self._decode_handle(row.get("recovery_handle")),
        )

    @staticmethod
    def encode_effect(effect: EffectReceipt | None) -> str | None:
        if effect is None:
            return None
        payload = {
            "effect_id": effect.effect_id,
            "request_digest": effect.request_digest,
            "effect_class": effect.effect_class.value,
            "certainty": effect.certainty.value,
            "provider_instance_id": effect.provider_instance_id,
            "verification_required": effect.verification_required,
            "before_artifact": effect.before_artifact,
            "after_artifact": effect.after_artifact,
            "provider_receipt": effect.provider_receipt,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def decode_effect(text: str | None) -> EffectReceipt | None:
        if text is None:
            return None
        row = json.loads(text)
        return EffectReceipt(
            row["effect_id"], row["request_digest"], EffectClass(row["effect_class"]),
            EffectCertainty(row["certainty"]), row.get("provider_instance_id"),
            bool(row.get("verification_required", False)), row.get("before_artifact"),
            row.get("after_artifact"), row.get("provider_receipt"),
        )

    @staticmethod
    def completion_digest(consumption: EffectCompletionEvidence | None) -> str | None:
        if consumption is None:
            return None
        return canonical_digest({
            "completion_key": consumption.completion_key,
            "completion_operation_id": consumption.completion_operation_id,
            "consumer_component_digest": consumption.consumer_component_digest,
            "consumer_generation": consumption.consumer_generation,
        })

    @staticmethod
    def encode_consumption(consumption: EffectCompletionEvidence | None) -> tuple[str | None, str | None]:
        if consumption is None:
            return None, None
        payload = {
            "completion_key": consumption.completion_key,
            "completion_operation_id": consumption.completion_operation_id,
            "consumer_component_digest": consumption.consumer_component_digest,
            "consumer_generation": consumption.consumer_generation,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")), EffectJournalDocumentCodec.completion_digest(consumption)

    @staticmethod
    def decode_consumption(text: str | None, expected_digest: str | None) -> EffectCompletionEvidence | None:
        if text is None:
            if expected_digest is not None:
                raise ValueError("effect completion digest exists without payload")
            return None
        row = json.loads(text)
        payload = {
            "completion_key": row["completion_key"],
            "completion_operation_id": row["completion_operation_id"],
            "consumer_component_digest": row["consumer_component_digest"],
            "consumer_generation": row.get("consumer_generation"),
        }
        if canonical_digest(payload) != expected_digest:
            raise ValueError("effect completion document checksum mismatch")
        return EffectCompletionEvidence(**payload)

    def encode_record(self, record: EffectIntentRecord) -> EncodedEffectIntentRecord:
        intent_json, intent_digest = self.encode_intent(record.intent)
        consumption_json, completion_digest = self.encode_consumption(record.consumption)
        if record.consumption_digest is not None and record.consumption_digest != completion_digest:
            raise ValueError(f"effect completion digest mismatch: {record.intent.intent_id}")
        return EncodedEffectIntentRecord(
            record.intent.intent_id, intent_json, intent_digest, record.intent.request_digest,
            record.intent.run_id, record.intent.lifetime_id, record.phase.value,
            self.encode_effect(record.effect), record.effect_digest,
            consumption_json, completion_digest,
        )

    def decode_record(self, encoded: EncodedEffectIntentRecord) -> EffectIntentRecord:
        try:
            raw = json.loads(encoded.intent_json)
            if not isinstance(raw, dict):
                raise EffectJournalIntegrityError(
                    f"effect intent document must be an object: {encoded.intent_id}"
                )
            if canonical_digest(raw) != encoded.intent_digest:
                raise EffectJournalIntegrityError(
                    f"effect intent document checksum mismatch: {encoded.intent_id}"
                )
            intent = self.decode_intent(encoded.intent_json)
            self._require_index_match(encoded.intent_id, "intent_id", encoded.intent_id, intent.intent_id)
            self._require_index_match(
                encoded.intent_id, "request_digest", encoded.request_digest, intent.request_digest
            )
            self._require_index_match(encoded.intent_id, "run_id", encoded.run_id, intent.run_id)
            self._require_index_match(
                encoded.intent_id, "lifetime_id", encoded.lifetime_id, intent.lifetime_id
            )

            phase = EffectIntentPhase(encoded.phase)
            effect = self.decode_effect(encoded.effect_json)
            computed_effect_digest = effect_digest(effect)
            if encoded.effect_digest != computed_effect_digest:
                raise EffectJournalIntegrityError(
                    f"effect journal effect checksum mismatch: {encoded.intent_id}"
                )
            if effect is not None and effect.request_digest != intent.request_digest:
                raise EffectJournalIntegrityError(
                    f"effect journal receipt/request mismatch: {encoded.intent_id}"
                )
            consumption = self.decode_consumption(
                encoded.consumption_json, encoded.consumption_digest
            )
            record = EffectIntentRecord(
                intent,
                phase,
                effect,
                encoded.effect_digest,
                consumption,
                encoded.consumption_digest,
            )
            self._validate_phase(record)
            return record
        except EffectJournalIntegrityError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EffectJournalIntegrityError(
                f"effect journal record is invalid: {encoded.intent_id}"
            ) from exc

    @staticmethod
    def _validate_phase(record: EffectIntentRecord) -> None:
        phase = record.phase
        effect = record.effect
        consumption = record.consumption
        if phase is EffectIntentPhase.PREPARED:
            if effect is not None or consumption is not None:
                raise EffectJournalIntegrityError(
                    "PREPARED effect journal record cannot carry result/completion evidence"
                )
            return
        if phase in {EffectIntentPhase.RESULT_RECORDED, EffectIntentPhase.RECONCILED}:
            if consumption is not None:
                raise EffectJournalIntegrityError(
                    "non-terminal effect journal record cannot carry completion evidence"
                )
            if phase is EffectIntentPhase.RECONCILED and effect is None:
                raise EffectJournalIntegrityError(
                    "RECONCILED effect journal record requires reconciliation evidence"
                )
            return
        if phase is EffectIntentPhase.CONSUMED:
            if (
                effect is None
                or effect.verification_required
                or effect.certainty not in {
                    EffectCertainty.EFFECT_CONFIRMED,
                    EffectCertainty.EFFECT_REJECTED,
                }
                or consumption is None
            ):
                raise EffectJournalIntegrityError(
                    "CONSUMED effect journal record lacks authoritative effect/completion evidence"
                )
            return
        if phase is EffectIntentPhase.NOT_APPLIED:
            if (
                effect is None
                or effect.verification_required
                or effect.certainty is not EffectCertainty.NO_EFFECT
                or consumption is not None
            ):
                raise EffectJournalIntegrityError(
                    "NOT_APPLIED effect journal record lacks authoritative NO_EFFECT evidence"
                )
            return
        raise EffectJournalIntegrityError(f"unsupported effect journal phase: {phase}")


__all__ = ["EffectJournalDocumentCodec"]
