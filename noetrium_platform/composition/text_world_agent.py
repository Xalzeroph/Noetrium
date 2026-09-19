from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, ActionResult, Observation
from noetrium_platform.capabilities.environment.text_world.api import TextWorldPort
from noetrium_platform.capabilities.participant.agent.api import (
    AgentActionStep,
    AgentObservation,
    AgentStepReceipt,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, ExecutionContext, JsonObject


def _agent_effect_certainty(certainty: EffectCertainty | None) -> str:
    if certainty is EffectCertainty.EFFECT_CONFIRMED:
        return "confirmed"
    if certainty in {EffectCertainty.EFFECT_REJECTED, EffectCertainty.NO_EFFECT}:
        return "rejected"
    if certainty is EffectCertainty.EFFECT_POSSIBLE:
        return "possible"
    return "unknown"


def text_world_agent_observation(observation: Observation) -> AgentObservation:
    if not isinstance(observation, Observation):
        raise TypeError("text-world agent bridge requires Observation")
    state: JsonObject = {"environment_payload": observation.payload}
    evidence: JsonObject = {
        "environment_observation_id": observation.observation_id,
        "environment_generation": observation.generation,
    }
    return AgentObservation(
        observation_id=observation.observation_id,
        generation=observation.generation,
        state=state,
        modality="text_world",
        artifact_refs=observation.artifact_refs,
        evidence_payload=evidence,
    )


class TextWorldAgentObservationPort:
    """Mechanical Environment Observation -> AgentObservation projection."""

    def __init__(self, world: TextWorldPort) -> None:
        self._world = world

    def observe(self, context: ExecutionContext) -> AgentObservation:
        return text_world_agent_observation(self._world.observe(context))


class TextWorldAgentActionExecutorPort:
    """Mechanical AgentActionStep -> TextWorld ActionRequest projection.

    Scientific action semantics remain downstream. The bridge forwards the
    typed action payload exactly and projects the environment receipt back into
    the generic Agent Step ABI.
    """

    def __init__(self, world: TextWorldPort) -> None:
        self._world = world

    def execute(self, step: AgentActionStep, context: ExecutionContext) -> AgentStepReceipt:
        if not isinstance(step, AgentActionStep):
            raise TypeError("text-world agent bridge requires AgentActionStep")
        vocabulary = tuple(item.value for item in self._world.spec.action_vocabulary)
        if vocabulary and step.action_type not in vocabulary:
            raise ValueError(f"text-world action type is not admitted by environment spec: {step.action_type}")
        result = self._world.act(
            ActionRequest(
                action_id=step.action_id,
                action_type=step.action_type,
                payload=dict(step.payload),
                context=context,
            )
        )
        if not isinstance(result, ActionResult):
            raise TypeError("text-world environment returned an invalid ActionResult")
        if result.action_id != step.action_id:
            raise ValueError("text-world action result identity mismatch")
        effect = result.effect
        verified = None if effect is None else effect.certainty in {
            EffectCertainty.EFFECT_CONFIRMED,
            EffectCertainty.EFFECT_REJECTED,
            EffectCertainty.NO_EFFECT,
        }
        return AgentStepReceipt(
            action_id=step.action_id,
            action_type=step.action_type,
            skill_id=step.skill_id,
            sequence_id=step.sequence_id,
            accepted=result.accepted,
            verified=verified,
            observation=None if result.observation is None else text_world_agent_observation(result.observation),
            effect_id=None if effect is None else effect.effect_id,
            effect_certainty=_agent_effect_certainty(None if effect is None else effect.certainty),
            diagnostics=dict(result.diagnostics),
            payload={"environment_action_id": result.action_id},
        )


__all__ = [
    "TextWorldAgentActionExecutorPort",
    "TextWorldAgentObservationPort",
    "text_world_agent_observation",
]
