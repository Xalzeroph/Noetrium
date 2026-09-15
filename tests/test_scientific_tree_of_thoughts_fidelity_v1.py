from __future__ import annotations

import pytest

from research.reproductions.tree_of_thoughts import (
    TREE_OF_THOUGHTS_REFERENCE_FIDELITY,
    ThoughtCandidate,
    TreeSearchFrontier,
    assign_duplicate_zero_values,
    greedy_select,
    sampling_probabilities,
)


def test_tree_of_thoughts_reference_search_modes_are_pinned() -> None:
    fidelity = TREE_OF_THOUGHTS_REFERENCE_FIDELITY
    assert fidelity.source_artifact == "src/tot/methods/bfs.py"
    assert fidelity.generation_modes == ("sample", "propose")
    assert fidelity.evaluation_modes == ("vote", "value")
    assert fidelity.selection_modes == ("sample", "greedy")
    assert fidelity.initial_frontier == ("",)


def test_duplicate_candidate_value_is_zeroed_locally() -> None:
    rows = assign_duplicate_zero_values(("a", "b", "a"), (0.9, 0.5, 0.9))
    assert [row.value for row in rows] == [0.9, 0.5, 0.0]


def test_greedy_selection_and_frontier_advance_remain_method_semantics() -> None:
    candidates = (
        ThoughtCandidate("one", 0.4),
        ThoughtCandidate("two", 0.9),
        ThoughtCandidate("three", 0.7),
    )
    selected = greedy_select(candidates, count=2)
    assert [row.text for row in selected] == ["two", "three"]
    frontier = TreeSearchFrontier(0, ("",)).advance(selected)
    assert frontier.depth == 1
    assert frontier.candidates == ("two", "three")


def test_weighted_sampling_distribution_is_explicit_but_rng_is_external() -> None:
    candidates = (ThoughtCandidate("a", 1.0), ThoughtCandidate("b", 3.0))
    assert sampling_probabilities(candidates) == (0.25, 0.75)
    with pytest.raises(ValueError, match="positive total"):
        sampling_probabilities((ThoughtCandidate("a", 0.0), ThoughtCandidate("b", 0.0)))
