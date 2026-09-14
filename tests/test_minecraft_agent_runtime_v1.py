from __future__ import annotations

import unittest

from noetrium_platform.capabilities.environment.minecraft.composition import (
    MinecraftBlueprintBlock,
    MinecraftBlueprintBuilder,
    MinecraftCognitionRunner,
    MinecraftRecipe,
    MinecraftResourcePlanner,
    MinecraftAgentSkillCatalog,
)
from noetrium_platform.capabilities.environment.runtime.api import ActionResult, Observation, action_request_digest
from noetrium_platform.capabilities.participant.agent.api import (
    AgentEvidencePort,
    AgentGoal,
    AgentPlannerPort,
    AgentPlanningRequest,
    AgentProgressPort,
    AgentSkillSelection,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


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
        planner = MinecraftResourcePlanner({
            "iron_ingot": MinecraftRecipe("iron_ingot", 1, {"raw_iron": 1}, "smelt"),
        })
        plan = planner.plan("iron_ingot", 2, {})
        self.assertEqual(tuple(step[0] for step in plan.steps), ("collect_block", "smelt_item"))
        self.assertEqual(plan.to_action_sequence(sequence_id="resource").steps[-1].action_type, "smelt_item")

        catalog = MinecraftAgentSkillCatalog()
        goal_plan = catalog.expand(
            AgentSkillSelection(
                "minecraft.resource_plan",
                {
                    "target": "iron_ingot",
                    "count": 2,
                    "inventory": {},
                    "recipes": {
                        "iron_ingot": {
                            "count": 1,
                            "ingredients": {"raw_iron": 1},
                            "process": "smelt",
                        }
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
