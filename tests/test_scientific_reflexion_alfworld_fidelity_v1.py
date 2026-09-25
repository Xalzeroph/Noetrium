from __future__ import annotations

import pytest

from research.reproductions.reflexion_alfworld import (
    REFLEXION_ALFWORLD_FIDELITY,
    ReflexionSemanticsError,
    ReflexionTaskState,
    accept_action_candidate,
    extract_failed_scenario,
    render_reflection_prompt,
    render_task_prompt,
)


def test_reflexion_alfworld_method_semantics_are_explicit() -> None:
    fidelity = REFLEXION_ALFWORLD_FIDELITY
    assert fidelity.max_trials == 10
    assert fidelity.max_turns_per_trial == 49
    assert fidelity.reference_action_model == "gpt-3.5-turbo"
    assert fidelity.reference_reflection_model == "text-davinci-003"
    assert fidelity.action_stop_sequences == ("\n",)
    assert fidelity.action_temperature(0) == 0.0
    assert fidelity.action_temperature(5) == 1.0
    assert fidelity.reflection_memory_window == 3


def test_reflexion_memory_is_method_owned_and_windowed() -> None:
    state = ReflexionTaskState("task:1", ("p0", "p1", "p2", "p3"))
    assert state.visible_reflections == ("p1", "p2", "p3")
    assert state.should_attempt is True
    assert state.should_reflect is True
    updated = state.append_reflection(" p4 ")
    assert updated.reflections[-1] == "p4"
    assert updated.visible_reflections == ("p2", "p3", "p4")
    solved = updated.mark_solved()
    assert solved.should_attempt is False
    assert solved.should_reflect is False
    with pytest.raises(ValueError, match="cannot add verbal memory"):
        solved.append_reflection("should not be accepted")


def test_reflexion_action_candidate_admission_matches_source_retry_policy() -> None:
    assert accept_action_candidate("look") is None
    assert accept_action_candidate(" open fridge ") == "open fridge"
    with pytest.raises(ReflexionSemanticsError, match="one line"):
        accept_action_candidate("open fridge\nlook")


def test_reflexion_task_prompt_injects_only_visible_recent_memory() -> None:
    state = ReflexionTaskState("task:1", ("old", "p1", "p2", "p3"))
    prompt = render_task_prompt("BASE", "find the mug", state)
    assert "old" not in prompt
    assert "p1" in prompt and "p2" in prompt and "p3" in prompt
    assert prompt.endswith("Here is the task:\nfind the mug")


def test_reflection_prompt_uses_failed_scenario_and_prior_plans() -> None:
    state = ReflexionTaskState("task:1", ("inspect sink first",))
    log = "header\nHere is the task:\nput the clean mug on the desk\n> action\nobservation"
    assert extract_failed_scenario(log).startswith("put the clean mug")
    prompt = render_reflection_prompt(
        failed_trial_log=log,
        state=state,
        few_shot_examples="EXAMPLE",
    )
    assert "EXAMPLE" in prompt
    assert "put the clean mug" in prompt
    assert "inspect sink first" in prompt
    assert prompt.endswith("New plan:")


def test_skipped_task_does_not_generate_reflection() -> None:
    state = ReflexionTaskState("task:1", skip=True)
    with pytest.raises(ReflexionSemanticsError, match="solved/skipped"):
        render_reflection_prompt(
            failed_trial_log="Here is the task:\nfoo",
            state=state,
            few_shot_examples="EXAMPLE",
        )
