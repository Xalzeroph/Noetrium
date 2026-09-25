from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    JsonObject,
    thaw_json,
)

from .contracts import ActionResult, Observation


def observation_payload(observation: Observation) -> JsonObject:
    if not isinstance(observation, Observation):
        raise TypeError("observation codec requires Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


def observation_from_payload(value: object) -> Observation:
    if not isinstance(value, Mapping):
        raise TypeError("observation payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("observation payload must decode to an object")
    refs = decoded.get("artifact_refs", ())
    if not isinstance(refs, (tuple, list)):
        raise TypeError("observation artifact_refs must be a sequence")
    return Observation(
        observation_id=decoded["observation_id"],
        generation=decoded["generation"],
        payload=decoded["payload"],
        artifact_refs=tuple(refs),
    )


def effect_receipt_payload(receipt: EffectReceipt) -> JsonObject:
    if not isinstance(receipt, EffectReceipt):
        raise TypeError("effect receipt codec requires EffectReceipt")
    return {
        "effect_id": receipt.effect_id,
        "request_digest": receipt.request_digest,
        "effect_class": receipt.effect_class.value,
        "certainty": receipt.certainty.value,
        "provider_instance_id": receipt.provider_instance_id,
        "verification_required": receipt.verification_required,
        "before_artifact": receipt.before_artifact,
        "after_artifact": receipt.after_artifact,
        "provider_receipt": receipt.provider_receipt,
    }


def effect_receipt_from_payload(value: object) -> EffectReceipt:
    if not isinstance(value, Mapping):
        raise TypeError("effect receipt payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("effect receipt payload must decode to an object")
    return EffectReceipt(
        effect_id=decoded["effect_id"],
        request_digest=decoded["request_digest"],
        effect_class=EffectClass(decoded["effect_class"]),
        certainty=EffectCertainty(decoded["certainty"]),
        provider_instance_id=decoded.get("provider_instance_id"),
        verification_required=decoded.get("verification_required", False),
        before_artifact=decoded.get("before_artifact"),
        after_artifact=decoded.get("after_artifact"),
        provider_receipt=decoded.get("provider_receipt"),
    )


def action_result_payload(result: ActionResult) -> JsonObject:
    if not isinstance(result, ActionResult):
        raise TypeError("action result codec requires ActionResult")
    return {
        "action_id": result.action_id,
        "accepted": result.accepted,
        "observation": (
            None
            if result.observation is None
            else observation_payload(result.observation)
        ),
        "effect": (
            None
            if result.effect is None
            else effect_receipt_payload(result.effect)
        ),
        "diagnostics": result.diagnostics,
    }


def action_result_from_payload(value: object) -> ActionResult:
    if not isinstance(value, Mapping):
        raise TypeError("action result payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("action result payload must decode to an object")
    diagnostics = decoded.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise TypeError("action result diagnostics must be an object")
    observation = decoded.get("observation")
    effect = decoded.get("effect")
    return ActionResult(
        action_id=decoded["action_id"],
        accepted=decoded["accepted"],
        observation=(
            None
            if observation is None
            else observation_from_payload(observation)
        ),
        effect=(
            None
            if effect is None
            else effect_receipt_from_payload(effect)
        ),
        diagnostics=diagnostics,
    )


__all__ = [
    "action_result_from_payload",
    "action_result_payload",
    "effect_receipt_from_payload",
    "effect_receipt_payload",
    "observation_from_payload",
    "observation_payload",
]
