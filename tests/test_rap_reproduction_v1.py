from __future__ import annotations

import pytest

from research.reproductions.rap_reasoning import (
    RAP_AUDITED_COMMIT,
    RAP_FIDELITY,
    RAPReward,
    RAPSimulatedTransition,
    backpropagate_mean_rewards,
    blocksworld_state_reward,
)


def test_rap_source_and_role_fidelity_are_frozen() -> None:
    assert RAP_AUDITED_COMMIT == "774817c228b3d5ddfc18de2318f3476128ecf6eb"
    assert RAP_FIDELITY.same_llm_reasoner_and_world_model is True
    assert RAP_FIDELITY.mcts_prior is True
    assert RAP_FIDELITY.mcts_reward_aggregation == "mean"
    assert RAP_FIDELITY.mcts_child_aggregation == "max"


def test_rap_reward_combines_action_prior_and_world_state_reward_exactly() -> None:
    assert RAPReward(0.25, 4.0, 0.5).combined == pytest.approx(1.0)
    assert RAPReward(-0.25, 4.0, 0.5).combined == pytest.approx(-0.25)
    assert RAPReward(0.25, -2.0, 0.5).combined == pytest.approx(-2.0)


def test_blocksworld_state_reward_separates_partial_progress_from_success() -> None:
    assert blocksworld_state_reward(satisfied_goals=0, total_goals=4) == pytest.approx(0.5)
    assert blocksworld_state_reward(satisfied_goals=2, total_goals=4) == pytest.approx(1.0)
    assert blocksworld_state_reward(satisfied_goals=4, total_goals=4) == pytest.approx(100.0)


def test_simulated_transition_terminal_semantics_match_paper_code() -> None:
    success = RAPSimulatedTransition(
        depth=2,
        action="stack red on blue",
        parent_state="red clear; blue clear",
        predicted_change="red becomes on blue",
        predicted_state="red on blue",
        reward=RAPReward(0.8, 100.0, 0.5),
    )
    depth_limit = RAPSimulatedTransition(
        depth=4,
        action="noop planning branch",
        parent_state="state-3",
        predicted_change="state unchanged",
        predicted_state="state-4",
        reward=RAPReward(0.8, 1.0, 0.5),
    )
    invalid = RAPSimulatedTransition(
        depth=2,
        action="invalid",
        parent_state="state-1",
        predicted_change="invalid transition",
        predicted_state="state-2",
        reward=RAPReward(0.8, -2.0, 0.5),
    )
    ongoing = RAPSimulatedTransition(
        depth=2,
        action="continue",
        parent_state="state-1",
        predicted_change="valid transition",
        predicted_state="state-2",
        reward=RAPReward(0.8, 1.0, 0.5),
    )

    assert success.is_terminal(max_depth=4) is True
    assert depth_limit.is_terminal(max_depth=4) is True
    assert invalid.is_terminal(max_depth=4) is True
    assert ongoing.is_terminal(max_depth=4) is False


def test_mean_backpropagation_matches_rap_reverse_path_update() -> None:
    rows = backpropagate_mean_rewards((3.0, 2.0, 1.0), discount=1.0)
    assert [row.cumulative_reward for row in rows] == pytest.approx([3.0, 5.0, 6.0])
    assert [row.coefficient for row in rows] == pytest.approx([2.0, 3.0, 4.0])
    assert [row.aggregated_reward for row in rows] == pytest.approx([1.5, 5.0 / 3.0, 1.5])
