"""Unit-native durable codec for the generic external-effect WAL."""
from __future__ import annotations

import base64
import json

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentPhase,
    EffectJournalIntegrityError,
    completion_field,
    effect_completion,
    effect_digest,
    effect_intent,
    effect_intent_record,
    effect_result_snapshot,
    intent_field,
    prepared_effect_handle,
    prepared_handle_field,
    record_field,
    result_snapshot_field,
)
from .persistence import EncodedEffectIntentRecord


class EffectJournalDocumentCodec:
    DOCUMENT_SCHEMA = "effect-intent-unit.v2"

    @staticmethod
    def _require_index_match(
        intent_id: str,
        field: str,
        observed: object,
        authoritative: object,
    ) -> None:
        if observed != authoritative:
            raise EffectJournalIntegrityError(
                f"effect journal {field} index mismatch: {intent_id}"
            )

    @staticmethod
    def _handle_payload(handle: NoetriumUnit | None) -> dict[str, object] | None:
        if handle is None:
            return None
        return {
            "request_id": prepared_handle_field(handle, "request_id"),
            "request_digest": prepared_handle_field(handle, "request_digest"),
            "provider_schema": prepared_handle_field(handle, "provider_schema"),
            "opaque_payload_b64": base64.b64encode(
                prepared_handle_field(handle, "opaque_payload")
            ).decode("ascii"),
            "payload_sha256": prepared_handle_field(handle, "payload_sha256"),
            "provider_instance_id": prepared_handle_field(
                handle, "provider_instance_id"
            ),
        }

    @staticmethod
    def _decode_handle(row: object) -> NoetriumUnit | None:
        if row is None:
            return None
        if not isinstance(row, dict):
            raise ValueError("invalid prepared effect handle document")
        payload = base64.b64decode(
            str(row["opaque_payload_b64"]).encode("ascii")
        )
        handle = prepared_effect_handle(
            request_id=str(row["request_id"]),
            request_digest=str(row["request_digest"]),
            provider_schema=str(row["provider_schema"]),
            opaque_payload=payload,
            provider_instance_id=(
                None
                if row.get("provider_instance_id") is None
                else str(row["provider_instance_id"])
            ),
        )
        if prepared_handle_field(handle, "payload_sha256") != row["payload_sha256"]:
            raise ValueError("prepared effect handle checksum mismatch")
        return handle

    def encode_intent(self, intent: NoetriumUnit) -> tuple[str, str]:
        payload = {
            "document_schema": self.DOCUMENT_SCHEMA,
            "intent_id": intent_field(intent, "intent_id"),
            "request_id": intent_field(intent, "request_id"),
            "operation_id": intent_field(intent, "operation_id"),
            "request_digest": intent_field(intent, "request_digest"),
            "provider_component_digest": intent_field(
                intent, "provider_component_digest"
            ),
            "run_id": intent_field(intent, "run_id"),
            "trace_id": intent_field(intent, "trace_id"),
            "study_id": intent_field(intent, "study_id"),
            "lifetime_id": intent_field(intent, "lifetime_id"),
            "task_id": intent_field(intent, "task_id"),
            "decision_cycle_id": intent_field(intent, "decision_cycle_id"),
            "checkpoint_id": intent_field(intent, "checkpoint_id"),
            "source_generation": intent_field(intent, "source_generation"),
            "recovery_handle": self._handle_payload(
                intent_field(intent, "recovery_handle")
            ),
        }
        return (
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            canonical_digest(payload),
        )

    def decode_intent(self, text: str) -> NoetriumUnit:
        row = json.loads(text)
        if row.get("document_schema") != self.DOCUMENT_SCHEMA:
            raise ValueError(
                f"unsupported effect intent document schema: "
                f"{row.get('document_schema')}"
            )
        return effect_intent(
            intent_id=str(row["intent_id"]),
            request_id=str(row["request_id"]),
            operation_id=str(row["operation_id"]),
            request_digest=str(row["request_digest"]),
            provider_component_digest=str(row["provider_component_digest"]),
            run_id=str(row["run_id"]),
            trace_id=str(row["trace_id"]),
            study_id=row.get("study_id"),
            lifetime_id=row.get("lifetime_id"),
            task_id=row.get("task_id"),
            decision_cycle_id=row.get("decision_cycle_id"),
            checkpoint_id=row.get("checkpoint_id"),
            source_generation=row.get("source_generation"),
            recovery_handle=self._decode_handle(row.get("recovery_handle")),
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
            effect_id=row["effect_id"],
            request_digest=row["request_digest"],
            effect_class=EffectClass(row["effect_class"]),
            certainty=EffectCertainty(row["certainty"]),
            provider_instance_id=row.get("provider_instance_id"),
            before_artifact=row.get("before_artifact"),
            after_artifact=row.get("after_artifact"),
            provider_receipt=row.get("provider_receipt"),
        )

    @staticmethod
    def encode_result_snapshot(snapshot: NoetriumUnit | None) -> str | None:
        if snapshot is None:
            return None
        payload = {
            "schema": result_snapshot_field(snapshot, "schema"),
            "opaque_payload_b64": base64.b64encode(
                result_snapshot_field(snapshot, "opaque_payload")
            ).decode("ascii"),
            "payload_sha256": result_snapshot_field(snapshot, "payload_sha256"),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def decode_result_snapshot(text: str | None) -> NoetriumUnit | None:
        if text is None:
            return None
        row = json.loads(text)
        if not isinstance(row, dict):
            raise ValueError("invalid effect result snapshot document")
        snapshot = effect_result_snapshot(
            schema=str(row["schema"]),
            opaque_payload=base64.b64decode(
                str(row["opaque_payload_b64"]).encode("ascii")
            ),
        )
        if result_snapshot_field(snapshot, "payload_sha256") != row["payload_sha256"]:
            raise ValueError("effect result snapshot checksum mismatch")
        return snapshot

    @staticmethod
    def completion_digest(consumption: NoetriumUnit | None) -> str | None:
        return None if consumption is None else consumption.semantic_digest

    @staticmethod
    def encode_consumption(
        consumption: NoetriumUnit | None,
    ) -> tuple[str | None, str | None]:
        if consumption is None:
            return None, None
        payload = {
            "completion_key": completion_field(consumption, "completion_key"),
            "completion_operation_id": completion_field(
                consumption, "completion_operation_id"
            ),
            "consumer_component_digest": completion_field(
                consumption, "consumer_component_digest"
            ),
            "consumer_generation": completion_field(
                consumption, "consumer_generation"
            ),
        }
        return (
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            consumption.semantic_digest,
        )

    @staticmethod
    def decode_consumption(
        text: str | None,
        expected_digest: str | None,
    ) -> NoetriumUnit | None:
        if text is None:
            if expected_digest is not None:
                raise ValueError("effect completion digest exists without payload")
            return None
        row = json.loads(text)
        completion = effect_completion(
            completion_key=str(row["completion_key"]),
            completion_operation_id=str(row["completion_operation_id"]),
            consumer_component_digest=str(row["consumer_component_digest"]),
            consumer_generation=row.get("consumer_generation"),
        )
        if completion.semantic_digest != expected_digest:
            raise ValueError("effect completion document checksum mismatch")
        return completion

    def encode_record(self, record: NoetriumUnit) -> EncodedEffectIntentRecord:
        intent = record_field(record, "intent")
        intent_json, intent_digest = self.encode_intent(intent)
        consumption = record_field(record, "consumption")
        consumption_json, completion_digest = self.encode_consumption(consumption)
        stored_completion_digest = record_field(record, "consumption_digest")
        if (
            stored_completion_digest is not None
            and stored_completion_digest != completion_digest
        ):
            raise ValueError(
                f"effect completion digest mismatch: "
                f"{intent_field(intent, 'intent_id')}"
            )
        return EncodedEffectIntentRecord(
            str(intent_field(intent, "intent_id")),
            intent_json,
            intent_digest,
            str(intent_field(intent, "request_digest")),
            str(intent_field(intent, "run_id")),
            intent_field(intent, "lifetime_id"),
            record_field(record, "phase").value,
            self.encode_effect(record_field(record, "effect")),
            record_field(record, "effect_digest"),
            self.encode_result_snapshot(record_field(record, "result_snapshot")),
            consumption_json,
            completion_digest,
        )

    def encode_transition(
        self,
        record: NoetriumUnit,
        *,
        prior: EncodedEffectIntentRecord,
    ) -> EncodedEffectIntentRecord:
        if not isinstance(prior, EncodedEffectIntentRecord):
            raise TypeError("effect transition encoding requires prior encoded record")
        intent = record_field(record, "intent")
        intent_id = str(intent_field(intent, "intent_id"))
        for label, observed, expected in (
            ("intent_id", intent_id, prior.intent_id),
            (
                "request_digest",
                intent_field(intent, "request_digest"),
                prior.request_digest,
            ),
            ("run_id", intent_field(intent, "run_id"), prior.run_id),
            (
                "lifetime_id",
                intent_field(intent, "lifetime_id"),
                prior.lifetime_id,
            ),
        ):
            if observed != expected:
                raise EffectJournalIntegrityError(
                    f"effect transition immutable {label} drifted: {intent_id}"
                )
        consumption = record_field(record, "consumption")
        consumption_json, completion_digest = self.encode_consumption(consumption)
        if (
            record_field(record, "consumption_digest") is not None
            and record_field(record, "consumption_digest") != completion_digest
        ):
            raise ValueError(
                f"effect completion digest mismatch: {intent_id}"
            )
        return EncodedEffectIntentRecord(
            prior.intent_id,
            prior.intent_json,
            prior.intent_digest,
            prior.request_digest,
            prior.run_id,
            prior.lifetime_id,
            record_field(record, "phase").value,
            self.encode_effect(record_field(record, "effect")),
            record_field(record, "effect_digest"),
            self.encode_result_snapshot(record_field(record, "result_snapshot")),
            consumption_json,
            completion_digest,
        )

    def decode_record(self, encoded: EncodedEffectIntentRecord) -> NoetriumUnit:
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
            self._require_index_match(
                encoded.intent_id,
                "intent_id",
                encoded.intent_id,
                intent_field(intent, "intent_id"),
            )
            self._require_index_match(
                encoded.intent_id,
                "request_digest",
                encoded.request_digest,
                intent_field(intent, "request_digest"),
            )
            self._require_index_match(
                encoded.intent_id,
                "run_id",
                encoded.run_id,
                intent_field(intent, "run_id"),
            )
            self._require_index_match(
                encoded.intent_id,
                "lifetime_id",
                encoded.lifetime_id,
                intent_field(intent, "lifetime_id"),
            )
            effect = self.decode_effect(encoded.effect_json)
            if encoded.effect_digest != effect_digest(effect):
                raise EffectJournalIntegrityError(
                    f"effect journal effect checksum mismatch: {encoded.intent_id}"
                )
            if (
                effect is not None
                and effect.request_digest
                != intent_field(intent, "request_digest")
            ):
                raise EffectJournalIntegrityError(
                    f"effect journal receipt/request mismatch: {encoded.intent_id}"
                )
            record = effect_intent_record(
                intent=intent,
                phase=EffectIntentPhase(encoded.phase),
                effect=effect,
                result_snapshot=self.decode_result_snapshot(
                    encoded.result_snapshot_json
                ),
                consumption=self.decode_consumption(
                    encoded.consumption_json,
                    encoded.consumption_digest,
                ),
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
    def _validate_phase(record: NoetriumUnit) -> None:
        phase = record_field(record, "phase")
        effect = record_field(record, "effect")
        consumption = record_field(record, "consumption")
        snapshot = record_field(record, "result_snapshot")
        if phase is EffectIntentPhase.PREPARED:
            if effect is not None or snapshot is not None or consumption is not None:
                raise EffectJournalIntegrityError(
                    "PREPARED effect journal record cannot carry result/completion evidence"
                )
            return
        if phase in {
            EffectIntentPhase.RESULT_RECORDED,
            EffectIntentPhase.RECONCILED,
        }:
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
                or effect.certainty
                not in {
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
                or effect.certainty is not EffectCertainty.NO_EFFECT
                or consumption is not None
            ):
                raise EffectJournalIntegrityError(
                    "NOT_APPLIED effect journal record lacks authoritative NO_EFFECT evidence"
                )
            return
        if phase is EffectIntentPhase.INDETERMINATE:
            if (
                effect is None
                or effect.certainty is not EffectCertainty.INDETERMINATE
                or consumption is not None
            ):
                raise EffectJournalIntegrityError(
                    "INDETERMINATE effect journal record lacks provider indeterminate evidence"
                )
            return
        raise EffectJournalIntegrityError(
            f"unsupported effect journal phase: {phase}"
        )


__all__ = ["EffectJournalDocumentCodec"]
