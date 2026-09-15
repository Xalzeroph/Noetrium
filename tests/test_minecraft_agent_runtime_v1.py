from __future__ import annotations

from tests._minecraft_agent_runtime_cases import MinecraftAgentRuntimeTest as _MinecraftAgentRuntimeTestBase

from noetrium_platform.capabilities.environment.minecraft.composition import MinecraftAgentCompletion
from noetrium_platform.capabilities.participant.agent.api import AgentGoal, AgentObservation, AgentStepReceipt


_MinecraftAgentRuntimeTestBase.__test__ = False


class MinecraftAgentRuntimeTest(_MinecraftAgentRuntimeTestBase):
    __test__ = True

    def test_completion_uses_exact_inventory_and_grounded_blueprint_position(self) -> None:
        completion = MinecraftAgentCompletion()
        inventory_goal = AgentGoal(
            "goal:exact-inventory",
            "collect stone",
            context={"success": {"kind": "inventory_any_min", "items": ["stone"], "count": 1}},
        )
        inventory_observation = AgentObservation(
            "obs:exact-inventory",
            "world-v1",
            {"inventory": {"stone_pickaxe": 4}},
        )
        inventory_decision = completion.evaluate(
            inventory_goal,
            inventory_observation,
            planner_finished=False,
            last_receipt=None,
        )
        self.assertFalse(inventory_decision.terminal)
        self.assertIsNone(inventory_decision.success)

        all_inventory_goal = AgentGoal(
            "goal:all-inventory",
            "collect the complete target set",
            context={
                "success": {
                    "kind": "inventory_all_delta_min",
                    "items": {"stone": 1, "oak_log": 2},
                    "initial_inventory": {"stone": 1},
                }
            },
        )
        all_inventory_observation = AgentObservation(
            "obs:all-inventory",
            "world-v1",
            {"inventory": {"stone": 2, "oak_log": 2}},
        )
        all_inventory_decision = completion.evaluate(
            all_inventory_goal,
            all_inventory_observation,
            planner_finished=False,
            last_receipt=None,
        )
        self.assertTrue(all_inventory_decision.terminal)
        self.assertTrue(all_inventory_decision.success)

        blueprint_goal = AgentGoal(
            "goal:exact-blueprint",
            "place one oak plank at the target",
            context={
                "success": {
                    "kind": "blueprint_complete",
                    "blocks": [{
                        "item": "oak_planks",
                        "position": {"x": 2, "y": 64, "z": 3},
                    }],
                }
            },
        )
        receipt = AgentStepReceipt(
            "action:place",
            "place_block",
            "minecraft.build",
            "sequence:1",
            True,
            True,
            observation=AgentObservation(
                "obs:place",
                "world-v1",
                {},
                evidence_payload={
                    "events": [{
                        "kind": "action_result",
                        "payload": {
                            "outcome": {
                                "status": "applied",
                                "code": "BLOCK_PLACED",
                                "placed": "oak_planks",
                                "position": {"x": 2, "y": 64, "z": 3},
                            }
                        },
                    }]
                },
            ),
            effect_certainty="confirmed",
            payload={"item": "oak_planks", "position": {"x": 2, "y": 64, "z": 3}},
        )
        blueprint_decision = completion.evaluate(
            blueprint_goal,
            AgentObservation("obs:blueprint", "world-v1", {}),
            planner_finished=False,
            last_receipt=receipt,
        )
        self.assertTrue(blueprint_decision.terminal)
        self.assertTrue(blueprint_decision.success)

        malformed_position_goal = AgentGoal(
            "goal:malformed-position",
            "place one oak plank at a malformed target",
            context={
                "success": {
                    "kind": "blueprint_complete",
                    "blocks": [{
                        "item": "oak_planks",
                        "position": {"x": "not-a-coordinate", "y": 64, "z": 3},
                    }],
                }
            },
        )
        malformed_decision = completion.evaluate(
            malformed_position_goal,
            AgentObservation("obs:malformed-position", "world-v1", {}),
            planner_finished=False,
            last_receipt=receipt,
        )
        self.assertFalse(malformed_decision.terminal)
        self.assertIsNone(malformed_decision.success)
