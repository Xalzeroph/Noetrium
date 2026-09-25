from __future__ import annotations

import math
import pytest

from research.reproductions.lats_webshop import (
    LATS_WEBSHOP_FIDELITY,
    LatsBranchState,
    backpropagated_mean,
    is_successful_terminal,
    uct_score,
)


def test_lats_matched_protocol_is_frozen() -> None:
    fidelity = LATS_WEBSHOP_FIDELITY
    assert fidelity.max_iterations == 30
    assert fidelity.implementation_default_iterations == 50
    assert fidelity.task_start_index == 0
    assert fidelity.task_end_index == 50
    assert fidelity.reference_model == "gpt-3.5-turbo"
    assert fidelity.temperature == 1.0
    assert fidelity.max_depth == 15
    assert fidelity.root_expansion_multiplier == 2
    assert fidelity.rollout_candidate_count == 5
    assert fidelity.value_evaluation_sample_count == 1


def test_lats_uct_matches_reference_edge_semantics() -> None:
    assert math.isinf(uct_score(value=0.0, visits=0, parent_visits=1))
    assert uct_score(value=-0.5, visits=0, parent_visits=1) == -0.5
    score = uct_score(value=2.0, visits=2, parent_visits=8)
    assert score == pytest.approx(1.0 + math.sqrt(2.0 * math.log(8) / 2))


def test_lats_backprop_and_branch_state_do_not_own_environment_payload() -> None:
    value, visits = backpropagated_mean(current_value=0.4, visits=2, rollout_value=1.0)
    assert visits == 3
    assert value == pytest.approx(0.6)

    branch = LatsBranchState(
        node_id="node:1",
        depth=3,
        action="click[Buy Now]",
        observation="Your score (min 0.0, max 1.0): 1.0",
        environment_checkpoint_ref="artifact:env-checkpoint:abc",
        reward=1.0,
        terminal=True,
    )
    assert is_successful_terminal(branch)
    with pytest.raises(ValueError, match="checkpoint reference"):
        LatsBranchState("node:2", 1, "search[x]", "obs", "")
