from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import MethodAgentRequest
from noetrium_platform.research.reproduction import ReproductionAssetKind

from research.reproductions.deps_minecraft import (
    DEPSGoal,
    DEPSGoalSelection,
    DEPSPlannerAgentLoop,
    DEPSPlannerMode,
    DEPSPlannerResponse,
    DEPSSelectorAgentLoop,
    DEPS_MINECRAFT_FIDELITY,
    DEPS_MINECRAFT_METHOD_PROGRAM,
    REPRODUCTION,
    deps_should_replan,
)


class _Planner:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "planner": "deps-test",
            "implementation_revision": 1,
        })

    def generate(self, request, context):
        del context
        if request.mode is DEPSPlannerMode.INITIAL_PLAN:
            return DEPSPlannerResponse(
                text="",
                dialogue="Human: obtain wood\n",
                goals=(),
                model_receipt={"mode": request.mode.value},
            )
        return DEPSPlannerResponse(
            text=f"{request.mode.value}-text",
            dialogue=request.dialogue + f"{request.mode.value}\n",
            model_receipt={"mode": request.mode.value},
        )


class _Selector:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "selector": "deps-test",
            "implementation_revision": 1,
        })

    def select(self, request, context):
        del context
        return DEPSGoalSelection(
            selected_index=len(request.goals) - 1,
            estimated_steps=tuple(float(i + 1) for i in range(len(request.goals))),
            selector_receipt={"policy": "test-last"},
        )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="deps-test-run",
        trace_id="deps-test-trace",
        span_id="deps-test-span",
        task_id="deps-test-task",
    )


def test_deps_fidelity_preserves_released_control_bounds() -> None:
    f = DEPS_MINECRAFT_FIDELITY
    assert f.failure_feedback_order == (
        "failed_step_description",
        "inventory_description",
        "failure_explanation",
        "replan_request",
    )
    assert f.craft_replan_step_threshold == 150
    assert f.smelt_replan_step_threshold == 200
    assert f.replan_round_limit == 12
    assert f.selector_release_complete is False


def test_deps_replan_triggers_match_release_boundaries() -> None:
    mine = DEPSGoal("mine_log", "mine", {"log": 1}, {"wooden_pickaxe": 1}, 1)
    craft = DEPSGoal("craft_planks", "craft", {"planks": 4}, {}, 2)
    smelt = DEPSGoal("smelt_iron", "smelt", {"iron_ingot": 1}, {}, 3)

    assert deps_should_replan(
        mine,
        goal_episode_steps=1,
        precondition_satisfied=False,
    )
    assert not deps_should_replan(
        mine,
        goal_episode_steps=1,
        precondition_satisfied=True,
    )
    assert not deps_should_replan(
        craft,
        goal_episode_steps=150,
        precondition_satisfied=True,
    )
    assert deps_should_replan(
        craft,
        goal_episode_steps=151,
        precondition_satisfied=True,
    )
    assert not deps_should_replan(
        smelt,
        goal_episode_steps=200,
        precondition_satisfied=True,
    )
    assert deps_should_replan(
        smelt,
        goal_episode_steps=201,
        precondition_satisfied=True,
    )


def test_deps_planner_loop_preserves_released_fallback_goal() -> None:
    loop = DEPSPlannerAgentLoop(_Planner())
    result = loop.run(MethodAgentRequest(
        agent_id="deps.planner",
        goal=None,
        view={
            "mode": "initial_plan",
            "task_question": "Obtain one log",
            "task_group": "basic",
            "dialogue": "",
            "inventory": (),
            "failed_goal": None,
        },
        input_value=None,
        previous_value=None,
        context=_context(),
    ))
    goals = result.state_update["goal_list"]
    assert len(goals) == 1
    assert goals[0]["name"] == "mine_log"
    assert goals[0]["goal_type"] == "mine"
    assert goals[0]["object"] == {"log": 1}


def test_deps_selector_loop_keeps_selector_as_explicit_method_seam() -> None:
    goals = (
        DEPSGoal("mine_log", "mine", {"log": 1}, {}, 1),
        DEPSGoal("craft_planks", "craft", {"planks": 4}, {}, 2),
    )
    loop = DEPSSelectorAgentLoop(_Selector())
    result = loop.run(MethodAgentRequest(
        agent_id="deps.selector",
        goal=None,
        view={
            "goals": tuple(goal.payload() for goal in goals),
            "inventory": (),
            "task_question": "Obtain planks",
        },
        input_value=None,
        previous_value=None,
        context=_context(),
    ))
    assert result.state_update["selected_index"] == 1
    assert result.state_update["selected_goal"]["name"] == "craft_planks"
    assert result.state_update["selector_estimated_steps"] == (1.0, 2.0)


def test_deps_method_program_exposes_interactive_planning_chain() -> None:
    program = DEPS_MINECRAFT_METHOD_PROGRAM
    node_ids = tuple(node.node_id for node in program.nodes)
    for required in (
        "initial_plan",
        "select_goal",
        "prepare_execute",
        "execute_goal",
        "failure_description",
        "explain_failure",
        "replan",
        "after_replan",
        "return",
    ):
        assert required in node_ids
    assert "environment.act" in program.required_capabilities
    assert "deps.selector.receipt" in program.evidence_obligations


def test_deps_reproduction_is_protocol_bound_with_explicit_selector_delta() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind("method_program") in kinds
    assert any("selector.py" in delta.description for delta in REPRODUCTION.deltas)
