from __future__ import annotations

import pytest

from research.reproductions.react_alfworld import REACT_ALFWORLD_RUN_SPEC, ReactAlfworldRunSpec


def test_react_alfworld_run_spec_matches_reference_protocol() -> None:
    spec = REACT_ALFWORLD_RUN_SPEC
    assert spec.method_id == "react"
    assert spec.benchmark_id == "alfworld"
    assert spec.expected_task_count == 134
    assert spec.max_turns == 49
    assert spec.terminal_authority == "environment"
    assert spec.success_signal == "info.won"


def test_react_alfworld_run_spec_rejects_planner_owned_termination() -> None:
    with pytest.raises(ValueError, match="environment-driven"):
        ReactAlfworldRunSpec(terminal_authority="planner")
