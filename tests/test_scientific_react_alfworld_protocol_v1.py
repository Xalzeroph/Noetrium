from __future__ import annotations

from research.benchmarks.alfworld import (
    ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
    ALFWORLD_PAPER_EVAL_REVISION,
    ALFWORLD_PAPER_EVAL_SPLIT,
    ALFWORLD_TASK_FAMILIES,
)
from research.reproductions.react_alfworld.definition import REPRODUCTION
from research.reproductions.react_alfworld.fidelity import REACT_ALFWORLD_FIDELITY
from research.reproductions.react_alfworld.source import SOURCES


def test_react_uses_typed_reproduction_authorities() -> None:
    assert REPRODUCTION.package == "react_alfworld"
    assert REPRODUCTION.identity.method_id == "react"
    source = {row.lane_id: row for row in SOURCES.lanes}["official_react_repo"]
    assert source.repository == "https://github.com/ysymyth/ReAct"
    assert source.commit == "19c6bae532250cf57bd7465d7f5a87edf2fda8f6"
    assert "alfworld.ipynb" in source.artifacts


def test_react_execution_semantics_live_in_typed_assets_not_projection_json() -> None:
    assert ALFWORLD_PAPER_EVAL_REVISION == "json_2.1.1"
    assert ALFWORLD_PAPER_EVAL_SPLIT == "eval_out_of_distribution"
    assert ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT == 134
    assert len(ALFWORLD_TASK_FAMILIES) == 6
    assert REACT_ALFWORLD_FIDELITY.max_turns == 49
    assert REACT_ALFWORLD_FIDELITY.think_prefix == "think:"
    assert REACT_ALFWORLD_FIDELITY.think_observation == "OK."
    assert REACT_ALFWORLD_FIDELITY.think_steps_environment is True
    assert REACT_ALFWORLD_FIDELITY.reference_model == "text-davinci-002"


def test_react_reported_targets_remain_claim_metadata() -> None:
    claims = {row.claim_id: row for row in REPRODUCTION.reported_results}
    assert claims["react_palm_mean"].value == 57
    assert claims["react_palm_best"].value == 71
    assert claims["act_palm_best"].value == 45
    assert claims["react_im_palm_best"].value == 53
    assert claims["released_code_davinci002"].value == 78.4
    assert claims["react_palm_mean"].qualifiers["reported_model_lane"]["roles"][0]["model"] == "PaLM-540B"
    assert claims["released_code_davinci002"].qualifiers["reported_model_lane"]["roles"][0]["model"] == "text-davinci-002"
