from __future__ import annotations

from noetrium.platform import run_method_program
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from research.reproductions.rap_reasoning import (
    RAP_BLOCKSWORLD_METHOD_PROGRAM,
    RAP_FIDELITY,
    rap_blocksworld_initial_state,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="rap-blocksworld-run",
        trace_id="trace",
        span_id="span",
        study_id="rap-blocksworld",
        task_id="blocksworld:test.pddl",
        decision_cycle_id="mcts",
        participant_generations=(),
    )


class _DeterministicRAPAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, request):
        self.calls.append(request.agent_id)
        if request.agent_id == "rap.reasoner":
            current = request.view["current_node"]
            assert current["node_id"] == "n0"
            return MethodAgentResult(
                value=(
                    {
                        "action": "stack red on blue",
                        "action_prior": 1.0,
                    },
                )
            )
        if request.agent_id == "rap.world_model":
            return MethodAgentResult(
                value={
                    "predicted_change": "red becomes on top of blue",
                    "predicted_state": "the red block is on top of the blue block",
                    "world_state_reward": 100.0,
                }
            )
        raise AssertionError(f"unexpected RAP agent id: {request.agent_id}")


def test_rap_method_program_preserves_prior_mcts_tree_across_ten_rollouts(tmp_path) -> None:
    agent = _DeterministicRAPAgent()
    result = run_method_program(
        RAP_BLOCKSWORLD_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(execution=_context(), agent_loop=agent),
        initial_state=rap_blocksworld_initial_state(
            initial_state="the red block and blue block are on the table",
            goal="the red block is on top of the blue block",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED, result.failure
    assert result.value["rollouts"] == RAP_FIDELITY.rollouts == 10
    assert result.value["plan_actions"] == ("stack red on blue",)
    assert result.value["best_score"] == 5.0

    tree = {row["node_id"]: row for row in result.value["tree"]}
    assert tree["n0"]["visits"] == 10
    assert tree["n1"]["visits"] == 10
    assert tree["n1"]["r0"] == 1.0
    assert tree["n1"]["r1"] == 100.0
    assert tree["n1"]["reward"] == 10.0

    # Expansion/world-model evaluation is cached in method state. Later
    # rollouts reuse the same tree node exactly as the official prior-MCTS
    # implementation reuses self.children and node reward.
    assert agent.calls.count("rap.reasoner") == 1
    assert agent.calls.count("rap.world_model") == 1
    visits = dict(result.visit_counts)
    assert visits["select"] == 10
    assert visits["backpropagate"] == 10
    assert visits["rollout"] == 10


def test_rap_study_and_method_program_share_one_typed_released_configuration() -> None:
    config = RAP_BLOCKSWORLD_METHOD_PROGRAM.configuration
    assert config["rollouts"] == RAP_FIDELITY.rollouts == 10
    assert config["max_depth"] == RAP_FIDELITY.max_depth == 4
    assert config["n_sample_confidence"] == RAP_FIDELITY.n_sample_confidence == 10
    assert config["alpha"] == RAP_FIDELITY.alpha == 0.5
    assert config["r1_default"] == RAP_FIDELITY.r1_default == 0.5
    assert config["exploration_weight"] == RAP_FIDELITY.exploration_weight == 1.0
    assert config["discount"] == RAP_FIDELITY.discount == 1.0
