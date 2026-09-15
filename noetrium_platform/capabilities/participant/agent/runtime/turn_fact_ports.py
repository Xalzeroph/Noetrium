from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest

from ..api.cognition import (
    AgentActionStep,
    AgentObservation,
    AgentPlanningRequest,
    AgentSkillSelection,
    AgentStepReceipt,
    action_summary_payload,
)
from ..api.cognition_ports import AgentActionExecutorPort, AgentObservationPort, AgentPlannerPort
from .turn_facts import AgentTurnFactBuffer, AgentTurnFactKind


def _observation_payload(observation: AgentObservation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "modality": observation.modality,
        "state_digest": observation.state_digest,
        "state": dict(observation.state),
        "evidence_payload": dict(observation.evidence_payload),
    }


class FactRecordingObservationPort:
    """Observe normally, then propose the exact model-visible observation fact."""

    def __init__(self, delegate: AgentObservationPort, facts: AgentTurnFactBuffer) -> None:
        self._delegate = delegate
        self._facts = facts

    def observe(self, context: ExecutionContext) -> AgentObservation:
        observation = self._delegate.observe(context)
        if not isinstance(observation, AgentObservation):
            raise TypeError("agent observation port returned an invalid observation")
        self._facts.append(
            AgentTurnFactKind.OBSERVATION,
            context=context,
            payload=_observation_payload(observation),
            artifact_refs=observation.artifact_refs,
        )
        return observation


class FactRecordingPlannerPort:
    """Record planning input identity and the planner's typed decision."""

    def __init__(self, delegate: AgentPlannerPort, facts: AgentTurnFactBuffer) -> None:
        self._delegate = delegate
        self._facts = facts

    def plan(self, request: AgentPlanningRequest) -> AgentSkillSelection:
        self._facts.append(
            AgentTurnFactKind.PLANNING_INPUT,
            context=request.context,
            payload={
                "goal_digest": request.goal.digest,
                "observation_digest": request.observation.state_digest,
                "memory_generation": request.memory.generation,
                "memory_query_id": request.memory.query_id,
                "memory_artifacts": list(request.memory.artifacts),
                "step": request.step,
                "plan_call": request.plan_call,
                "prior_action_digests": [
                    canonical_digest(action_summary_payload(summary))
                    for summary in request.prior_actions
                ],
                "available_skill_ids": [skill.skill_id for skill in request.available_skills],
                "retrieved_skill_ids": [skill.skill_id for skill in request.retrieved_skills],
                "last_effect_id": None if request.last_receipt is None else request.last_receipt.effect_id,
            },
            artifact_refs=request.memory.artifacts,
        )
        selection = self._delegate.plan(request)
        if not isinstance(selection, AgentSkillSelection):
            raise TypeError("agent planner returned an invalid skill selection")
        self._facts.append(
            AgentTurnFactKind.DECISION,
            context=request.context,
            payload={
                "skill_id": selection.skill_id,
                "arguments": dict(selection.arguments),
                "completion_claim": selection.completion_claim,
                "rationale": selection.rationale,
                "priority": selection.priority,
            },
        )
        return selection


class FactRecordingActionExecutorPort:
    """Record an action proposal, its effect receipt, and receipt-carried observation."""

    def __init__(self, delegate: AgentActionExecutorPort, facts: AgentTurnFactBuffer) -> None:
        self._delegate = delegate
        self._facts = facts

    def execute(self, step: AgentActionStep, context: ExecutionContext) -> AgentStepReceipt:
        self._facts.append(
            AgentTurnFactKind.ACTION,
            context=context,
            payload={
                "action_id": step.action_id,
                "action_type": step.action_type,
                "skill_id": step.skill_id,
                "sequence_id": step.sequence_id,
                "sequence_index": step.sequence_index,
                "payload": dict(step.payload),
                "interruptible": step.interruptible,
                "rationale": step.rationale,
                "timeout_s": float(step.timeout_s),
            },
        )
        receipt = self._delegate.execute(step, context)
        if not isinstance(receipt, AgentStepReceipt):
            raise TypeError("agent action executor returned an invalid receipt")
        self._facts.append(
            AgentTurnFactKind.EFFECT,
            context=context,
            payload={
                "action_id": receipt.action_id,
                "action_type": receipt.action_type,
                "skill_id": receipt.skill_id,
                "sequence_id": receipt.sequence_id,
                "accepted": receipt.accepted,
                "verified": receipt.verified,
                "effect_id": receipt.effect_id,
                "effect_certainty": receipt.effect_certainty,
                "diagnostics": dict(receipt.diagnostics),
                "payload": dict(receipt.payload),
            },
        )
        if receipt.observation is not None:
            self._facts.append(
                AgentTurnFactKind.OBSERVATION,
                context=context,
                payload=_observation_payload(receipt.observation),
                artifact_refs=receipt.observation.artifact_refs,
            )
        return receipt


__all__ = [
    "FactRecordingActionExecutorPort",
    "FactRecordingObservationPort",
    "FactRecordingPlannerPort",
]
