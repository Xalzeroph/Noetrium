from __future__ import annotations

from typing import Mapping

from noetrium_platform.capabilities.environment.api import ActionRequest, EnvironmentSession
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, JsonObject
from noetrium_platform.capabilities.participant.agent.api import (
    AgentActionExecutorPort, AgentActionStep, AgentObservation, AgentStepReceipt, JsonValue,
)
from noetrium_platform.capabilities.environment.minecraft.api import validate_minecraft_action
from noetrium_platform.capabilities.environment.minecraft.api.contracts import MinecraftJsonValue

def _json_value(value: MinecraftJsonValue | tuple[MinecraftJsonValue, ...]) -> MinecraftJsonValue | list[MinecraftJsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _json_mapping(value: Mapping[str, MinecraftJsonValue]) -> dict[str, JsonValue]:
    return {str(key): _json_value(item) for key, item in value.items()}



def _minecraft_decision_state(payload: object) -> Mapping[str, MinecraftJsonValue]:
    if not isinstance(payload, Mapping):
        raise ValueError("Minecraft observation payload must be a mapping")
    view = payload.get("decision_view")
    if not isinstance(view, Mapping) or view.get("kind") != "minecraft_decision_view.v1":
        raise ValueError("Minecraft observation is missing canonical decision_view")
    state = view.get("state")
    if not isinstance(state, Mapping):
        raise ValueError("Minecraft decision_view must contain mapping state")
    return state


def _agent_effect_certainty(certainty: EffectCertainty | None) -> str:
    if certainty is EffectCertainty.EFFECT_CONFIRMED:
        return "confirmed"
    if certainty in {EffectCertainty.EFFECT_REJECTED, EffectCertainty.NO_EFFECT}:
        return "rejected"
    if certainty is EffectCertainty.EFFECT_POSSIBLE:
        return "possible"
    return "unknown"


def _grounded_action_receipt(receipt: AgentStepReceipt | None) -> bool:
    return bool(
        receipt
        and receipt.accepted
        and receipt.effect_certainty == "confirmed"
        and receipt.verified is not False
    )


def _agent_sequence(sequence: MinecraftPlannedSequence) -> AgentActionSequence:
    return AgentActionSequence(
        sequence.sequence_id,
        sequence.skill_id,
        tuple(
            AgentActionStep(
                action_id=f"{sequence.sequence_id}:{step.sequence_index}",
                action_type=step.action_type,
                payload=_json_mapping(step.payload),
                skill_id=sequence.skill_id,
                sequence_id=sequence.sequence_id,
                sequence_index=step.sequence_index,
                rationale=step.rationale,
                timeout_s=float(getattr(step, "timeout_s", 120.0)),
            )
            for step in sequence.steps
        ),
        completion_claim=sequence.completion_claim,
    )


class MinecraftAgentObservationPort:
    """Composition adapter from the MC EnvironmentSession to rich cognition state."""

    def __init__(self, session: EnvironmentSession) -> None:
        self._session = session
        self._sequence = 0

    def observe(self, context) -> AgentObservation:
        raw = self._session.observe(context)
        state = _minecraft_decision_state(raw.payload)
        self._sequence += 1
        return AgentObservation(
            f"agent:{raw.observation_id}:{self._sequence}", raw.generation, _json_mapping(state),
            modality="minecraft.rich_world", artifact_refs=raw.artifact_refs,
            evidence_payload=_json_mapping(dict(raw.payload)),
        )


class MinecraftAgentActionExecutor(AgentActionExecutorPort):
    def __init__(self, session: EnvironmentSession) -> None:
        self._session = session

    def execute(self, step: AgentActionStep, context) -> AgentStepReceipt:
        payload = validate_minecraft_action(step.action_type, step.payload)
        result = self._session.act(ActionRequest(step.action_id, step.action_type, payload, context))
        diagnostics = dict(result.diagnostics)
        if result.effect is not None:
            effect_payload = {
                "effect_id": result.effect.effect_id,
                "request_digest": result.effect.request_digest,
                "certainty": getattr(result.effect.certainty, "value", result.effect.certainty),
                "before_artifact": result.effect.before_artifact,
                "after_artifact": result.effect.after_artifact,
                "provider_receipt": result.effect.provider_receipt,
            }
            diagnostics.setdefault("effect_receipt", effect_payload)
            anchors = diagnostics.get("anchors")
            if not isinstance(anchors, (list, tuple)) or not anchors:
                anchors = [f"effect:{result.effect.effect_id}"]
                if result.effect.before_artifact:
                    anchors.append(f"before:{result.effect.before_artifact}")
                if result.effect.after_artifact:
                    anchors.append(f"after:{result.effect.after_artifact}")
                diagnostics["anchors"] = anchors
        verified_value = diagnostics.get("verified")
        verified = verified_value if isinstance(verified_value, bool) else None
        observation = None
        if result.observation is not None:
            state = _minecraft_decision_state(result.observation.payload)
            observation = AgentObservation(
                f"agent:{result.observation.observation_id}", result.observation.generation,
                _json_mapping(dict(state)), modality="minecraft.rich_world",
                artifact_refs=result.observation.artifact_refs,
                evidence_payload=_json_mapping(dict(result.observation.payload)),
            )
        certainty = _agent_effect_certainty(
            result.effect.certainty if result.effect is not None else None
        )
        effect_id = result.effect.effect_id if result.effect is not None else None
        return AgentStepReceipt(
            step.action_id, step.action_type, step.skill_id, step.sequence_id, bool(result.accepted), verified,
            observation=observation, effect_id=effect_id,
            effect_certainty=certainty, diagnostics=_json_mapping(diagnostics),
            payload=_json_mapping(payload),
        )



__all__ = ["MinecraftAgentActionExecutor", "MinecraftAgentObservationPort"]
