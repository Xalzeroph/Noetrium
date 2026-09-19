from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane
from .source import SOURCE_OFFICIAL_TOT_REPO



@dataclass(frozen=True, slots=True)
class TreeOfThoughtsReferenceFidelity:
    """Core BFS reference semantics audited from the official ToT repository."""

    source: MethodSourceLane = SOURCE_OFFICIAL_TOT_REPO
    generation_modes: tuple[str, ...] = ("sample", "propose")
    evaluation_modes: tuple[str, ...] = ("vote", "value")
    selection_modes: tuple[str, ...] = ("sample", "greedy")
    initial_frontier: tuple[str, ...] = ("",)
    duplicate_candidate_value: float = 0.0
    value_prompt_cache: bool = True

    def __post_init__(self) -> None:
        if self.generation_modes != ("sample", "propose"):
            raise ValueError("Tree of Thoughts generation modes drifted")
        if self.evaluation_modes != ("vote", "value"):
            raise ValueError("Tree of Thoughts evaluation modes drifted")
        if self.selection_modes != ("sample", "greedy"):
            raise ValueError("Tree of Thoughts selection modes drifted")
        if self.initial_frontier != ("",) or self.duplicate_candidate_value != 0.0:
            raise ValueError("Tree of Thoughts frontier semantics drifted")


@dataclass(frozen=True, slots=True)
class TreeOfThoughtsGame24Fidelity:
    """Released Game24 BFS experiment settings shared by Study and UMM compilation."""

    task_start_index: int = 900
    task_end_index_exclusive: int = 1000
    backend: str = "gpt-4"
    temperature: float = 0.7
    generation_mode: str = "propose"
    evaluation_mode: str = "value"
    selection_mode: str = "greedy"
    n_generate_sample: int = 1
    n_evaluate_sample: int = 3
    n_select_sample: int = 5
    search_steps: int = 4

    def __post_init__(self) -> None:
        if (self.task_start_index, self.task_end_index_exclusive) != (900, 1000):
            raise ValueError("Tree of Thoughts Game24 task range drifted")
        if self.backend != "gpt-4" or self.temperature != 0.7:
            raise ValueError("Tree of Thoughts Game24 model settings drifted")
        if (self.generation_mode, self.evaluation_mode, self.selection_mode) != (
            "propose",
            "value",
            "greedy",
        ):
            raise ValueError("Tree of Thoughts Game24 BFS modes drifted")
        if (self.n_generate_sample, self.n_evaluate_sample, self.n_select_sample, self.search_steps) != (
            1,
            3,
            5,
            4,
        ):
            raise ValueError("Tree of Thoughts Game24 search budget drifted")


TREE_OF_THOUGHTS_REFERENCE_FIDELITY = TreeOfThoughtsReferenceFidelity()
TREE_OF_THOUGHTS_GAME24_FIDELITY = TreeOfThoughtsGame24Fidelity()


__all__ = [
    "TREE_OF_THOUGHTS_GAME24_FIDELITY",
    "TREE_OF_THOUGHTS_REFERENCE_FIDELITY",
    "TreeOfThoughtsGame24Fidelity",
    "TreeOfThoughtsReferenceFidelity",
]
