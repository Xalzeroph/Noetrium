from __future__ import annotations

from noetrium_platform.capabilities.participant.agent.api import (
    AgentActionStep,
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentPlanningRequest,
    AgentSkillSelection,
    AgentStepReceipt,
)
from noetrium_platform.capabilities.participant.agent.runtime.turn_fact_ports import (
    FactRecordingActionExecutorPort,
    FactRecordingObservationPort,
    FactRecordingPlannerPort,
)
from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import (
    AgentTurnFactBuffer,
    AgentTurnFactKind,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


_CONTEXT = ExecutionContext(
    "run:1",
    "trace:1",
    "span:1",
    task_id="goal:1",
    decision_cycle_id="goal:1:plan:0",
)


class _Observation:
    def observe(self, context):
        assert context is _CONTEXT
        return AgentObservation(
            "obs:1",
            "world-v1",
            {"text": "You are in a room."},
            modality="text",
            artifact_refs=("artifact:obs:1",),
            evidence_payload={"source": "text-world"},
        )


class _Planner:
    def plan(self, request):
        assert request.goal.goal_id == "goal:1"
        return AgentSkillSelection("act", {"command": "open fridge 1"}, rationale="inspect")


class _Executor:
    def execute(self, step, context):
        assert context is _CONTEXT
        return AgentStepReceipt(
            step.action_id,
            step.action_type,
            step.skill_id,
            step.sequence_id,
            True,
            True,
            observation=AgentObservation(
                "obs:2",
                "world-v2",
                {"text": "The fridge is open."},
                modality="text",
            ),
            effect_id="effect:1",
            effect_certainty="confirmed",
            payload={"provider_receipt": "r1"},
        )


def test_fact_recording_ports_preserve_agent_turn_order_and_exact_observation_state() -> None:
    facts = AgentTurnFactBuffer("session:1")
    observation_port = FactRecordingObservationPort(_Observation(), facts)
    planner_port = FactRecordingPlannerPort(_Planner(), facts)
    executor_port = FactRecordingActionExecutorPort(_Executor(), facts)

    observation = observation_port.observe(_CONTEXT)
    request = AgentPlanningRequest(
        goal=AgentGoal("goal:1", "inspect the fridge"),
        observation=observation,
        memory=AgentMemoryContext("", "memory-v1"),
        step=0,
        plan_call=0,
        prior_actions=(),
        context=_CONTEXT,
    )
    selection = planner_port.plan(request)
    step = AgentActionStep(
        "action:1",
        "text_world.command",
        dict(selection.arguments),
        selection.skill_id,
        "sequence:1",
        0,
        rationale=selection.rationale,
    )
    receipt = executor_port.execute(step, _CONTEXT)

    assert receipt.effect_id == "effect:1"
    assert tuple(fact.kind for fact in facts.facts) == (
        AgentTurnFactKind.OBSERVATION,
        AgentTurnFactKind.PLANNING_INPUT,
        AgentTurnFactKind.DECISION,
        AgentTurnFactKind.ACTION,
        AgentTurnFactKind.EFFECT,
        AgentTurnFactKind.OBSERVATION,
    )
    assert facts.facts[0].payload["state"] == {"text": "You are in a room."}
    assert facts.facts[-1].payload["state"] == {"text": "The fridge is open."}
    assert facts.facts[0].artifact_refs == ("artifact:obs:1",)
    assert all(
        fact.sequence == index
        for index, fact in enumerate(facts.facts, start=1)
    )
    assert all(
        facts.facts[index].previous_fact_digest == facts.facts[index - 1].fact_digest
        for index in range(1, len(facts.facts))
    )
