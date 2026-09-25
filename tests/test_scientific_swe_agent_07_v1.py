from __future__ import annotations

import pytest

from research.reproductions.swe_agent_swebench import (
    SWE_AGENT_07_FIDELITY,
    SweAgentAciState,
    SweAgentTurn,
    visible_observation_suffix,
)


def test_swe_agent_07_protocol_is_frozen() -> None:
    fidelity = SWE_AGENT_07_FIDELITY
    assert fidelity.parser_type == "thought_action"
    assert fidelity.editor_window_lines == 100
    assert fidelity.editor_overlap_lines == 2
    assert fidelity.visible_observation_history == 5


def test_swe_agent_turn_requires_feedback_before_next_command() -> None:
    state = SweAgentAciState()
    turn = SweAgentTurn("Inspect the repository first.", "ls -a")
    pending = state.issue(turn)
    with pytest.raises(ValueError, match="wait for feedback"):
        pending.issue(SweAgentTurn("Read the file.", "cat README.md"))
    ready = pending.observe("README.md\nsrc")
    assert ready.turn_index == 1
    assert not ready.awaiting_observation


def test_swe_agent_submit_is_method_terminal_intent_and_history_is_bounded_view() -> None:
    submit = SweAgentTurn("The fix and tests are complete.", "submit")
    assert submit.submit_requested
    observations = tuple(f"o{i}" for i in range(8))
    assert visible_observation_suffix(observations) == ("o3", "o4", "o5", "o6", "o7")
    with pytest.raises(ValueError, match="one command"):
        SweAgentTurn("Do two things.", "ls\npwd")
