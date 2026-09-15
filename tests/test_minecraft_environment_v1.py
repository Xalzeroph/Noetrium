from __future__ import annotations

from tests._minecraft_environment_cases import *  # noqa: F401,F403

from noetrium_platform.capabilities.environment.minecraft.composition import MinecraftAgentCompletion
from noetrium_platform.capabilities.participant.agent.api import AgentGoal, AgentObservation, AgentStepReceipt


def test_planner_finish_requires_action_receipt() -> None:
    completion = MinecraftAgentCompletion()
    goal = AgentGoal("goal:planner-finish", "finish", context={"success": {"kind": "planner_finish"}})
    observation = AgentObservation("obs:planner-finish", "world-v1", {})
    decision = completion.evaluate(goal, observation, planner_finished=True, last_receipt=None)
    assert decision.terminal is False
    assert decision.success is None


def test_last_action_verified_requires_grounded_non_contradictory_receipt() -> None:
    completion = MinecraftAgentCompletion()
    goal = AgentGoal(
        "goal:last-action-grounded",
        "finish",
        context={"success": {"kind": "last_action_verified"}},
    )
    observation = AgentObservation("obs:last-action-grounded", "world-v1", {})
    contradictory = AgentStepReceipt(
        "action:rejected", "wait", "minecraft.wait", "sequence:1", False, True,
        effect_id="minecraft-action:rejected", effect_certainty="rejected",
    )
    uncertain = AgentStepReceipt(
        "action:possible", "wait", "minecraft.wait", "sequence:2", True, True,
        effect_id="minecraft-action:possible", effect_certainty="possible",
    )
    grounded = AgentStepReceipt(
        "action:confirmed", "wait", "minecraft.wait", "sequence:3", True, True,
        effect_id="minecraft-action:confirmed", effect_certainty="confirmed",
    )

    assert completion.evaluate(
        goal, observation, planner_finished=False, last_receipt=contradictory
    ).terminal is False
    assert completion.evaluate(
        goal, observation, planner_finished=False, last_receipt=uncertain
    ).terminal is False
    grounded_decision = completion.evaluate(
        goal, observation, planner_finished=False, last_receipt=grounded
    )
    assert grounded_decision.terminal is True
    assert grounded_decision.success is True


def test_planner_finish_requires_grounded_action_receipt() -> None:
    completion = MinecraftAgentCompletion()
    goal = AgentGoal("goal:planner-grounded", "finish", context={"success": {"kind": "planner_finish"}})
    observation = AgentObservation("obs:planner-grounded", "world-v1", {})
    accepted_unverified = AgentStepReceipt(
        "action:unverified", "wait", "minecraft.wait", "sequence:1", True, False,
        effect_id="minecraft-action:unverified", effect_certainty="possible",
    )
    confirmed = AgentStepReceipt(
        "action:confirmed", "wait", "minecraft.wait", "sequence:2", True, None,
        effect_id="minecraft-action:confirmed", effect_certainty="confirmed",
    )
    verified = AgentStepReceipt(
        "action:verified", "wait", "minecraft.wait", "sequence:3", True, True,
        effect_id="minecraft-action:verified", effect_certainty="confirmed",
    )

    assert completion.evaluate(
        goal, observation, planner_finished=True, last_receipt=accepted_unverified
    ).terminal is False
    confirmed_decision = completion.evaluate(
        goal, observation, planner_finished=True, last_receipt=confirmed
    )
    verified_decision = completion.evaluate(
        goal, observation, planner_finished=True, last_receipt=verified
    )
    assert confirmed_decision.success is True
    assert verified_decision.success is True


def test_dead_minecraft_episode_is_terminal_failure_not_success() -> None:
    completion = MinecraftAgentCompletion()
    goal = AgentGoal("goal:dead", "survive", context={"success": {"kind": "planner_finish"}})
    observation = AgentObservation("obs:dead", "world-v1", {"health": 0})
    decision = completion.evaluate(goal, observation, planner_finished=False, last_receipt=None)
    assert decision.terminal is True
    assert decision.success is False
    assert decision.reason == "minecraft_player_dead"
