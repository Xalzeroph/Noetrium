from __future__ import annotations

import unittest

from noetrium_platform.capabilities.environment.minecraft.composition import (
    MinecraftBlueprintBlock,
    MinecraftBlueprintBuilder,
    MinecraftCognitionRunner,
    MinecraftRecipeCatalog,
    MinecraftResourcePlanner,
    MinecraftAgentSkillCatalog,
    MinecraftAgentCompletion,
)
from noetrium_platform.capabilities.environment.runtime.api import ActionResult, Observation, action_request_digest
from noetrium_platform.capabilities.participant.agent.api import (
    AgentEvidencePort,
    AgentGoal,
    AgentPlannerPort,
    AgentPlanningRequest,
    AgentProgressPort,
    AgentSkillSelection,
    AgentObservation,
    AgentStepReceipt,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext
from noetrium_platform.capabilities.participant.agent.runtime.memory import InMemoryAgentMemory


class _Session:
    def __init__(self) -> None:
        self.state = {
            "health": 20,
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory": {},
            "nearby_entities": [],
            "hostile_entities": [],
        }
        self.sequence = 0
        self.observe_calls = 0

    def observe(self, context: ExecutionContext) -> Observation:
        del context
        self.observe_calls += 1
        self.sequence += 1
        return Observation(f"obs:{self.sequence}", "world-v1", {"state": dict(self.state)})

    def act(self, request):
        if request.action_type == "collect_block":
            inventory = dict(self.state["inventory"])
            inventory[request.payload["block"]] = inventory.get(request.payload["block"], 0) + request.payload["count"]
            self.state["inventory"] = inventory
        self.sequence += 1
        effect = EffectReceipt(
            effect_id=f"minecraft-action:{request.action_id}",
            request_digest=action_request_digest(request),
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id="minecraft:test-session",
            verification_required=False,
            provider_receipt=request.action_id,
        )
        return ActionResult(
            request.action_id,
            True,
            Observation(f"obs:{self.sequence}", "world-v1", {"state": dict(self.state)}),
            effect,
            {"verified": True},
        )


class _Planner(AgentPlannerPort):
    def plan(self, request: AgentPlanningRequest) -> AgentSkillSelection:
        if request.observation.state.get("inventory", {}).get("oak_log", 0) >= 1:
            return AgentSkillSelection("minecraft.collect_block", {"block": "oak_log", "count": 1}, completion_claim=True)
        return AgentSkillSelection("minecraft.mine", {"block": "oak_log", "count": 1}, rationale="obtain the target resource")


class _Evidence(AgentEvidencePort):
    def __init__(self) -> None:
        self.rows = []

    def ingest(self, observation, context) -> None:
        self.rows.append((observation.observation_id, context.task_id))


class _Progress(AgentProgressPort):
    def __init__(self) -> None:
        self.checkpoints = []

    def persist(self, checkpoint, context) -> None:
        self.checkpoints.append((checkpoint, context.task_id))


class MinecraftAgentRuntimeTest(unittest.TestCase):
    def test_full_minecraft_cognition_loop(self) -> None:
        session = _Session()
        evidence = _Evidence()
        progress = _Progress()
        runner = MinecraftCognitionRunner(
            session,
            planner=_Planner(),
            evidence=evidence,
            progress=progress,
            memory=InMemoryAgentMemory(),
            clock=lambda: 1.0,
        )
        result = runner.run(
            AgentGoal(
                "goal:oak",
                "collect one oak log",
                context={"success": {"kind": "inventory_min", "item": "oak_log", "count": 1}},
                max_steps=4,
            ),
            ExecutionContext("run", "trace", "span", participant_generations=(("environment", "world-v1"),)),
            session_id="agent-session",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.action_receipts[0].effect_certainty, "confirmed")
        self.assertGreaterEqual(len(evidence.rows), 2)
        self.assertEqual(session.observe_calls, 1)
        self.assertTrue(progress.checkpoints)
        self.assertEqual(runner.ports.memory.records[-1].kind, "spatial_landmark")

    def test_resource_plan_and_blueprint_are_typed(self) -> None:
        iron_catalog = MinecraftRecipeCatalog.from_minecraft_data(
            {
                "iron_ingot": [{
                    "type": "furnace",
                    "input": [{"id": 4, "count": 1}],
                    "output": [{"id": 5, "count": 1}],
                }],
            },
            [{"id": 4, "name": "raw_iron"}, {"id": 5, "name": "iron_ingot"}],
            [{"id": 44, "name": "iron_ore", "drops": [4]}],
            version="1.21.8",
        )
        planner = MinecraftResourcePlanner(iron_catalog)
        plan = planner.plan("iron_ingot", 2, {})
        self.assertEqual(tuple(step[0] for step in plan.steps), ("collect_block", "smelt_item"))
        self.assertEqual(plan.to_action_sequence(sequence_id="resource").steps[-1].action_type, "smelt_item")

        alternatives = MinecraftRecipeCatalog.from_minecraft_data(
            {"4": [{
                "inShape": [[[35, 159], 35], [None, 35]],
                "result": {"id": 4, "count": 1},
            }]},
            [
                {"id": 35, "name": "oak_log"},
                {"id": 159, "name": "spruce_log"},
                {"id": 4, "name": "crafted_block"},
            ],
            [],
            version="1.21.8",
        )
        alternative_recipe = alternatives.recipes_for("crafted_block")[0]
        self.assertEqual(alternative_recipe.ingredients, {"oak_log": 2})
        self.assertEqual(alternative_recipe.ingredient_options, (("oak_log", "spruce_log"),))

        catalog = MinecraftRecipeCatalog.from_minecraft_data(
            {"5": [{"inShape": [[4, 4], [4, 4]], "result": {"id": 5, "count": 4}}]},
            [{"id": 4, "name": "oak_log"}, {"id": 5, "name": "oak_planks"}],
            [{"id": 49, "name": "oak_log", "drops": [4]}],
            version="1.21.8",
        )
        catalog_plan = MinecraftResourcePlanner(catalog).plan("oak_planks", 4, {})
        self.assertEqual(tuple(step[0] for step in catalog_plan.steps), ("collect_block", "craft_item"))

        catalog_goal = MinecraftAgentSkillCatalog().expand(
            AgentSkillSelection(
                "minecraft.resource_plan",
                {
                    "target": "oak_planks",
                    "count": 4,
                    "inventory": {},
                    "recipe_data": {
                        "recipes": {
                            "5": [{"inShape": [[4, 4], [4, 4]], "result": {"id": 5, "count": 4}}],
                        },
                        "items": [
                            {"id": 4, "name": "oak_log"},
                            {"id": 5, "name": "oak_planks"},
                        ],
                        "blocks": [{"id": 49, "name": "oak_log", "drops": [4]}],
                        "version": "1.21.8",
                    },
                },
            ),
            observation=None,  # type: ignore[arg-type]
            context=ExecutionContext("run", "trace", "span"),
            sequence_id="catalog-goal",
        )
        self.assertEqual(tuple(step.action_type for step in catalog_goal.steps), ("collect_block", "craft_item"))

        catalog = MinecraftAgentSkillCatalog()
        goal_plan = catalog.expand(
            AgentSkillSelection(
                "minecraft.resource_plan",
                {
                    "target": "iron_ingot",
                    "count": 2,
                    "inventory": {},
                    "recipe_data": {
                        "recipes": {
                            "iron_ingot": [{
                                "type": "furnace",
                                "input": [{"id": 4, "count": 1}],
                                "output": [{"id": 5, "count": 1}],
                            }],
                        },
                        "items": [
                            {"id": 4, "name": "raw_iron"},
                            {"id": 5, "name": "iron_ingot"},
                        ],
                        "blocks": [{"id": 44, "name": "iron_ore", "drops": [4]}],
                        "version": "1.21.8",
                    },
                },
            ),
            observation=None,  # type: ignore[arg-type]
            context=ExecutionContext("run", "trace", "span"),
            sequence_id="resource-goal",
        )
        self.assertEqual(tuple(step.action_type for step in goal_plan.steps), ("collect_block", "smelt_item"))

        blueprint = MinecraftBlueprintBuilder().build(
            (MinecraftBlueprintBlock({"x": 1, "y": 64, "z": 1}, "oak_planks", 0),),
            {},
            sequence_id="build",
        )
        self.assertEqual(blueprint.steps[0].action_type, "place_block")
        self.assertEqual(blueprint.steps[0].payload["item"], "oak_planks")

    def test_resource_plan_fails_closed_for_unknown_resource_sources(self) -> None:
        catalog = MinecraftRecipeCatalog.from_minecraft_data(
            {"5": [{"inShape": [[4]], "result": {"id": 5, "count": 1}}]},
            [{"id": 4, "name": "opaque_input"}, {"id": 5, "name": "crafted_item"}],
            [],
            version="1.21.8",
        )

        plan = MinecraftResourcePlanner(catalog).plan("crafted_item", 1, {})

        self.assertEqual(plan.steps, ())
        self.assertEqual(plan.missing, ("opaque_input", "crafted_item"))


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
        self.assertFalse(completion.is_complete(
            inventory_goal,
            inventory_observation,
            planner_finished=False,
            last_receipt=None,
        ))

        all_inventory_goal = AgentGoal(
            "goal:all-inventory",
            "collect the complete target set",
            context={"success": {"kind": "inventory_all_delta_min", "items": {"stone": 1, "oak_log": 2}, "initial_inventory": {"stone": 1}}},
        )
        all_inventory_observation = AgentObservation(
            "obs:all-inventory",
            "world-v1",
            {"inventory": {"stone": 2, "oak_log": 2}},
        )
        self.assertTrue(completion.is_complete(
            all_inventory_goal,
            all_inventory_observation,
            planner_finished=False,
            last_receipt=None,
        ))

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
        self.assertTrue(completion.is_complete(
            blueprint_goal,
            AgentObservation("obs:blueprint", "world-v1", {}),
            planner_finished=False,
            last_receipt=receipt,
        ))

        malformed_position_goal = AgentGoal(
            "goal:malformed-position",
            "place one oak plank at a malformed target",
            context={"success": {"kind": "blueprint_complete", "blocks": [{
                "item": "oak_planks", "position": {"x": "not-a-coordinate", "y": 64, "z": 3}
            }]}},
        )
        self.assertFalse(completion.is_complete(
            malformed_position_goal,
            AgentObservation("obs:malformed-position", "world-v1", {}),
            planner_finished=False,
            last_receipt=receipt,
        ))

    def test_high_level_skill_selection_expands_to_typed_sequence(self) -> None:
        catalog = MinecraftAgentSkillCatalog()
        described = {skill.skill_id for skill in catalog.describe()}
        self.assertTrue({"minecraft.build", "minecraft.resource_plan", "minecraft.explore", "minecraft.survive"} <= described)
        build = catalog.expand(
            AgentSkillSelection(
                "minecraft.build",
                {"blocks": [{"item": "oak_planks", "position": {"x": 1, "y": 64, "z": 1}, "level": 0}]},
            ),
            observation=None,  # type: ignore[arg-type]
            context=ExecutionContext("run", "trace", "span"),
            sequence_id="high-level-build",
        )
        self.assertEqual(build.steps[0].action_type, "place_block")


    def test_high_level_skills_accept_frozen_tuple_arrays_and_reject_invalid_shapes(self) -> None:
        catalog = MinecraftAgentSkillCatalog()
        context = ExecutionContext("run", "trace", "span")
        build = catalog.expand(
            AgentSkillSelection(
                "minecraft.build",
                {"blocks": ({"item": "oak_planks", "position": {"x": 1, "y": 64, "z": 1}, "level": 0},)},
            ),
            observation=None,  # type: ignore[arg-type]
            context=context,
            sequence_id="frozen-build",
        )
        self.assertEqual(build.steps[0].action_type, "place_block")

        plan = catalog.expand(
            AgentSkillSelection(
                "minecraft.resource_plan",
                {"steps": ({"action_type": "wait", "payload": {"ms": 1}},)},
            ),
            observation=None,  # type: ignore[arg-type]
            context=context,
            sequence_id="frozen-plan",
        )
        self.assertEqual(plan.steps[0].action_type, "wait")

        with self.assertRaises(ValueError):
            catalog.expand(
                AgentSkillSelection("minecraft.build", {"blocks": "not-an-array"}),
                observation=None,  # type: ignore[arg-type]
                context=context,
                sequence_id="invalid-build",
            )
        with self.assertRaises(ValueError):
            catalog.expand(
                AgentSkillSelection("minecraft.resource_plan", {"steps": {"bad": "shape"}}),
                observation=None,  # type: ignore[arg-type]
                context=context,
                sequence_id="invalid-plan",
            )



if __name__ == "__main__":
    unittest.main()
