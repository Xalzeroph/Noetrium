"""Durable effect/WAL schemas over the universal NoetriumUnit carrier."""
from __future__ import annotations

import base64
from collections.abc import Mapping
from enum import StrEnum
import hashlib

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.kernel.event import (
    causal_event,
    event_ref,
    event_field,
    is_event_unit,
)
from noetrium_platform.foundation.kernel.truth import TruthModality, modal_attributes
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role


class EffectIntentPhase(StrEnum):
    PREPARED = "prepared"
    RESULT_RECORDED = "result_recorded"
    RECONCILED = "reconciled"
    CONSUMED = "consumed"
    NOT_APPLIED = "not_applied"
    INDETERMINATE = "indeterminate"

    @property
    def terminal(self) -> bool:
        return self in {
            EffectIntentPhase.CONSUMED,
            EffectIntentPhase.NOT_APPLIED,
            EffectIntentPhase.INDETERMINATE,
        }


def _unit(
    kind: str,
    payload: Mapping[str, object],
    *,
    roles=(),
    modality: TruthModality,
) -> NoetriumUnit:
    frozen = freeze_json(dict(payload))
    if not isinstance(frozen, Mapping):
        raise TypeError("effect unit payload must remain an object")
    modality = TruthModality(modality)
    digest = canonical_digest({"kind": kind, "payload": frozen, "truth_modality": modality.value})
    return NoetriumUnit(
        f"{kind}:{digest}",
        schemas=(kind,),
        attributes=modal_attributes(modality, {"kind": kind, **dict(frozen)}),
        roles=tuple(roles),
        semantic_projection_digest=digest,
    )


def _is(value: object, kind: str) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == kind


def prepared_effect_handle(
    *,
    request_id: str,
    request_digest: str,
    provider_schema: str,
    opaque_payload: bytes,
    provider_instance_id: str | None = None,
) -> NoetriumUnit:
    payload = bytes(opaque_payload)
    if not request_id.strip() or not request_digest.strip() or not provider_schema.strip():
        raise ValueError("prepared effect handle identity fields must be non-empty")
    return _unit(
        "effect.prepared-handle",
        {
            "request_id": request_id,
            "request_digest": request_digest,
            "provider_schema": provider_schema,
            "opaque_payload_b64": base64.b64encode(payload).decode("ascii"),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "provider_instance_id": provider_instance_id,
        },
        modality=TruthModality.OBSERVED,
    )


def is_prepared_effect_handle(value: object) -> bool:
    return _is(value, "effect.prepared-handle")


def prepared_handle_field(handle: NoetriumUnit, name: str):
    if not is_prepared_effect_handle(handle):
        raise TypeError("prepared handle projection requires effect.prepared-handle Unit")
    if name == "opaque_payload":
        return base64.b64decode(str(handle.attribute("opaque_payload_b64")).encode("ascii"))
    return handle.attribute(name)


def effect_result_snapshot(*, schema: str, opaque_payload: bytes) -> NoetriumUnit:
    payload = bytes(opaque_payload)
    if type(schema) is not str or not schema.strip():
        raise ValueError("effect result snapshot schema must be non-empty")
    return _unit(
        "effect.result-snapshot",
        {
            "schema": schema,
            "opaque_payload_b64": base64.b64encode(payload).decode("ascii"),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
        modality=TruthModality.OBSERVED,
    )


def is_effect_result_snapshot(value: object) -> bool:
    return _is(value, "effect.result-snapshot")


def result_snapshot_field(snapshot: NoetriumUnit, name: str):
    if not is_effect_result_snapshot(snapshot):
        raise TypeError("result snapshot projection requires effect.result-snapshot Unit")
    if name == "opaque_payload":
        return base64.b64decode(str(snapshot.attribute("opaque_payload_b64")).encode("ascii"))
    return snapshot.attribute(name)


def effect_receipt_record(effect: EffectReceipt) -> NoetriumUnit:
    if not isinstance(effect, EffectReceipt):
        raise TypeError("effect receipt materialization requires EffectReceipt")
    return _unit(
        "effect.receipt",
        {
            "effect_id": effect.effect_id,
            "request_digest": effect.request_digest,
            "effect_class": effect.effect_class.value,
            "certainty": effect.certainty.value,
            "provider_instance_id": effect.provider_instance_id,
            "before_artifact": effect.before_artifact,
            "after_artifact": effect.after_artifact,
            "provider_receipt": effect.provider_receipt,
        },
        modality=TruthModality.OBSERVED,
    )


def effect_receipt_value(unit: NoetriumUnit) -> EffectReceipt:
    if not _is(unit, "effect.receipt"):
        raise TypeError("effect receipt projection requires effect.receipt Unit")
    return EffectReceipt(
        effect_id=str(unit.attribute("effect_id")),
        request_digest=str(unit.attribute("request_digest")),
        effect_class=EffectClass(str(unit.attribute("effect_class"))),
        certainty=EffectCertainty(str(unit.attribute("certainty"))),
        provider_instance_id=unit.attribute("provider_instance_id"),
        before_artifact=unit.attribute("before_artifact"),
        after_artifact=unit.attribute("after_artifact"),
        provider_receipt=unit.attribute("provider_receipt"),
    )


def effect_intent(
    *,
    intent_id: str,
    request_id: str,
    operation_id: str,
    request_digest: str,
    provider_component_digest: str,
    run_id: str,
    trace_id: str,
    study_id: str | None,
    lifetime_id: str | None,
    task_id: str | None,
    decision_cycle_id: str | None,
    checkpoint_id: str | None = None,
    source_generation: str | None = None,
    recovery_handle: NoetriumUnit | None = None,
) -> NoetriumUnit:
    if recovery_handle is not None and not _is(recovery_handle, "effect.prepared-handle"):
        raise TypeError("effect intent recovery handle must be effect.prepared-handle Unit")
    payload = {
        "intent_id": intent_id,
        "request_id": request_id,
        "operation_id": operation_id,
        "request_digest": request_digest,
        "provider_component_digest": provider_component_digest,
        "run_id": run_id,
        "trace_id": trace_id,
        "study_id": study_id,
        "lifetime_id": lifetime_id,
        "task_id": task_id,
        "decision_cycle_id": decision_cycle_id,
        "checkpoint_id": checkpoint_id,
        "source_generation": source_generation,
    }
    roles = () if recovery_handle is None else (role("recovery-handle", recovery_handle),)
    return _unit("effect.intent", payload, roles=roles, modality=TruthModality.DECLARED)


def build_effect_intent(
    *,
    request_id: str,
    request_digest: str,
    operation_id: str,
    provider_component: ComponentIdentity,
    context: ExecutionContext,
    source_generation: str | None = None,
    recovery_handle: NoetriumUnit | None = None,
    intent_namespace: str = "effect-intent",
) -> NoetriumUnit:
    if recovery_handle is not None:
        if (
            prepared_handle_field(recovery_handle, "request_id") != request_id
            or prepared_handle_field(recovery_handle, "request_digest") != request_digest
        ):
            raise ValueError("prepared effect handle does not match effect request identity")
    provider_digest = canonical_digest(provider_component)
    identity_material = {
        "request_id": request_id,
        "operation_id": operation_id,
        "provider_component_digest": provider_digest,
        "run_id": context.run_id,
        "study_id": context.study_id,
        "lifetime_id": context.lifetime_id,
        "task_id": context.task_id,
        "decision_cycle_id": context.decision_cycle_id,
        "checkpoint_id": context.checkpoint_id,
    }
    return effect_intent(
        intent_id=f"{intent_namespace}:{canonical_digest(identity_material)}",
        request_id=request_id,
        operation_id=operation_id,
        request_digest=request_digest,
        provider_component_digest=provider_digest,
        run_id=context.run_id,
        trace_id=context.trace_id,
        study_id=context.study_id,
        lifetime_id=context.lifetime_id,
        task_id=context.task_id,
        decision_cycle_id=context.decision_cycle_id,
        checkpoint_id=context.checkpoint_id,
        source_generation=source_generation,
        recovery_handle=recovery_handle,
    )


def intent_field(intent: NoetriumUnit, name: str):
    if not _is(intent, "effect.intent"):
        raise TypeError("effect intent projection requires effect.intent Unit")
    if name == "recovery_handle":
        rows = intent.units("recovery-handle")
        return None if not rows else rows[0]
    return intent.attribute(name)


def effect_completion(
    *,
    completion_key: str,
    completion_operation_id: str,
    consumer_component_digest: str,
    consumer_generation: str | None = None,
) -> NoetriumUnit:
    if not completion_key.strip() or not completion_operation_id.strip() or not consumer_component_digest.strip():
        raise ValueError("effect completion identity fields must be non-empty")
    return _unit(
        "effect.completion",
        {
            "completion_key": completion_key,
            "completion_operation_id": completion_operation_id,
            "consumer_component_digest": consumer_component_digest,
            "consumer_generation": consumer_generation,
        },
        modality=TruthModality.EVIDENCED,
    )


def completion_field(completion: NoetriumUnit, name: str):
    if not _is(completion, "effect.completion"):
        raise TypeError("effect completion projection requires effect.completion Unit")
    return completion.attribute(name)


def effect_intent_record(
    *,
    intent: NoetriumUnit,
    phase: EffectIntentPhase,
    effect: EffectReceipt | NoetriumUnit | None = None,
    result_snapshot: NoetriumUnit | None = None,
    consumption: NoetriumUnit | None = None,
) -> NoetriumUnit:
    if not _is(intent, "effect.intent"):
        raise TypeError("effect record intent must be effect.intent Unit")
    effect_unit = (
        None
        if effect is None
        else (effect if type(effect) is NoetriumUnit else effect_receipt_record(effect))
    )
    if effect_unit is not None and not _is(effect_unit, "effect.receipt"):
        raise TypeError("effect record receipt must be effect.receipt Unit")
    if result_snapshot is not None and not _is(result_snapshot, "effect.result-snapshot"):
        raise TypeError("effect record result must be effect.result-snapshot Unit")
    if consumption is not None and not _is(consumption, "effect.completion"):
        raise TypeError("effect record consumption must be effect.completion Unit")
    roles = [role("intent", intent)]
    if effect_unit is not None:
        roles.append(role("effect", effect_unit))
    if result_snapshot is not None:
        roles.append(role("result-snapshot", result_snapshot))
    if consumption is not None:
        roles.append(role("consumption", consumption))
    return _unit(
        "effect.record",
        {
            "phase": EffectIntentPhase(phase).value,
            "effect_digest": None if effect_unit is None else effect_unit.semantic_digest,
            "consumption_digest": None if consumption is None else consumption.semantic_digest,
        },
        roles=tuple(roles),
        modality=TruthModality.AUTHORIZED,
    )


def record_field(record: NoetriumUnit, name: str):
    if not _is(record, "effect.record"):
        raise TypeError("effect record projection requires effect.record Unit")
    if name == "phase":
        return EffectIntentPhase(str(record.attribute("phase")))
    if name == "intent":
        return record.one_unit("intent")
    if name == "effect":
        values = record.units("effect")
        return None if not values else effect_receipt_value(values[0])
    if name == "effect_unit":
        values = record.units("effect")
        return None if not values else values[0]
    if name == "result_snapshot":
        values = record.units("result-snapshot")
        return None if not values else values[0]
    if name == "consumption":
        values = record.units("consumption")
        return None if not values else values[0]
    return record.attribute(name)




def effect_record_event(
    record: NoetriumUnit,
    *,
    causal_parent: NoetriumUnit | None = None,
) -> NoetriumUnit:
    """Materialize one Authority transition as a causal Event Unit."""

    if not _is(record, "effect.record"):
        raise TypeError("effect event requires effect.record Unit")
    intent = record_field(record, "intent")
    intent_id = str(intent_field(intent, "intent_id"))
    domain = "effect." + canonical_digest(intent_id)[:32]
    parent_refs = ()
    if causal_parent is not None:
        if not is_event_unit(causal_parent):
            raise TypeError("effect causal parent must be system.event Unit")
        if event_field(causal_parent, "authority_domain") != domain:
            raise ValueError("effect causal parent crossed authority domain")
        parent_refs = (event_ref(causal_parent),)
    phase_value = record_field(record, "phase")
    phase = phase_value.value
    modality = (
        TruthModality.AUTHORIZED
        if phase_value in {
            EffectIntentPhase.PREPARED,
            EffectIntentPhase.CONSUMED,
        }
        else TruthModality.OBSERVED
    )
    evidence = tuple(
        value
        for value in (
            record_field(record, "effect_unit"),
            record_field(record, "result_snapshot"),
            record_field(record, "consumption"),
        )
        if value is not None
    )
    return causal_event(
        authority_domain=domain,
        generation=1,
        subject=record,
        operation="effect-transition",
        phase=phase,
        modality=modality,
        causal_parents=parent_refs,
        reads=(f"effect:{intent_id}",),
        writes=(f"effect:{intent_id}",),
        evidence=evidence,
        event_kind="effect.transition",
    )


def effect_record_from_event(event: NoetriumUnit) -> NoetriumUnit:
    if not is_event_unit(event) or not event.has_schema("effect.transition"):
        raise TypeError("effect event projection requires effect.transition Event Unit")
    subject = event_field(event, "subject")
    if type(subject) is not NoetriumUnit or not _is(subject, "effect.record"):
        raise TypeError("effect event subject must be effect.record Unit")
    return subject

def effect_digest(effect: EffectReceipt | None) -> str | None:
    return None if effect is None else effect_receipt_record(effect).semantic_digest


def consumption_digest(consumption: NoetriumUnit | None) -> str | None:
    if consumption is None:
        return None
    if not _is(consumption, "effect.completion"):
        raise TypeError("consumption digest requires effect.completion Unit")
    return consumption.semantic_digest


__all__ = [
    "EffectIntentPhase",
    "build_effect_intent",
    "completion_field",
    "consumption_digest",
    "effect_completion",
    "effect_digest",
    "effect_intent",
    "effect_intent_record",
    "effect_receipt_record",
    "effect_receipt_value",
    "effect_record_from_event",
    "effect_record_event",
    "effect_result_snapshot",
    "intent_field",
    "is_effect_result_snapshot",
    "is_prepared_effect_handle",
    "prepared_effect_handle",
    "prepared_handle_field",
    "record_field",
    "result_snapshot_field",
]
