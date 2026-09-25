from __future__ import annotations

import pytest

from research.reproductions.reflexion_alfworld import (
    REFLEXION_ALFWORLD_FIDELITY,
    ReflexionTaskState,
    should_reflect,
)


def test_reflexion_matched_protocol_is_frozen() -> None:
    fidelity = REFLEXION_ALFWORLD_FIDELITY
    assert fidelity.max_trials == 10
    assert fidelity.max_turns_per_trial == 49
    assert fidelity.reflection_memory_window == 3


def test_reflexion_reflects_only_after_failed_active_trial() -> None:
    before = ReflexionTaskState("task:1")
    failed = before.complete_trial(success=False)
    assert should_reflect(before, failed)
    reflected = failed.append_reflection("Search the cabinet before revisiting the table.")
    assert reflected.memory_view == ("Search the cabinet before revisiting the table.",)

    solved = reflected.complete_trial(success=True)
    assert not should_reflect(reflected, solved)
    with pytest.raises(ValueError, match="cannot consume another trial"):
        solved.complete_trial(success=False)


def test_reflexion_model_view_keeps_only_latest_three_reflections() -> None:
    state = ReflexionTaskState(
        "task:1",
        completed_trials=4,
        reflections=("r1", "r2", "r3", "r4"),
    )
    assert state.reflections == ("r1", "r2", "r3", "r4")
    assert state.memory_view == ("r2", "r3", "r4")
