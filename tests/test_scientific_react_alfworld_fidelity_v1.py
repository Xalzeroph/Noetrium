from __future__ import annotations

import pytest

from research.reproductions.react_alfworld import (
    REACT_ALFWORLD_FIDELITY,
    ReactProtocolError,
    is_think_action,
    normalize_model_action,
    render_react_alfworld_transcript,
    visible_observation,
)


def test_original_react_alfworld_fidelity_is_explicit() -> None:
    fidelity = REACT_ALFWORLD_FIDELITY

    assert fidelity.environment_split == "eval_out_of_distribution"
    assert fidelity.reference_model == "text-davinci-002"
    assert fidelity.temperature == 0.0
    assert fidelity.max_output_tokens == 100
    assert fidelity.stop_sequences == ("\n",)
    assert fidelity.max_turns == 49
    assert fidelity.expected_task_count == 134
    assert fidelity.demonstrations_per_task_family == 2
    assert len(fidelity.task_families) == 6


def test_react_model_action_is_exactly_one_line() -> None:
    assert normalize_model_action(" open fridge ") == "open fridge"
    with pytest.raises(ReactProtocolError, match="one line"):
        normalize_model_action("open fridge\nlook")


def test_react_think_is_method_semantics_not_environment_action() -> None:
    assert is_think_action("think: I should inspect the sink") is True
    assert visible_observation("think: I should inspect the sink", "provider text") == "OK."
    assert visible_observation("open fridge", "The fridge is open.") == "The fridge is open."


def test_react_transcript_matches_original_action_observation_shape() -> None:
    rendered = render_react_alfworld_transcript(
        base_prompt="BASE\n",
        initial_observation="You are in a room.",
        exchanges=(
            ("think: inspect first", "OK."),
            ("open fridge", "The fridge is open."),
        ),
    )

    assert rendered == (
        "BASE\nYou are in a room.\n>"
        " think: inspect first\nOK.\n>"
        " open fridge\nThe fridge is open.\n>"
    )
