from __future__ import annotations

from dataclasses import dataclass


TREE_OF_THOUGHTS_AUDITED_COMMIT = "8050e67d0e3a0fddc424d7fa5801538722a4c4cc"


@dataclass(frozen=True, slots=True)
class TreeOfThoughtsReferenceFidelity:
    """Core BFS reference semantics audited from the official ToT repository."""

    source_repository: str = "https://github.com/princeton-nlp/tree-of-thought-llm"
    audited_commit: str = TREE_OF_THOUGHTS_AUDITED_COMMIT
    source_artifact: str = "src/tot/methods/bfs.py"
    generation_modes: tuple[str, ...] = ("sample", "propose")
    evaluation_modes: tuple[str, ...] = ("vote", "value")
    selection_modes: tuple[str, ...] = ("sample", "greedy")
    initial_frontier: tuple[str, ...] = ("",)
    duplicate_candidate_value: float = 0.0
    value_prompt_cache: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Tree of Thoughts audited commit must be a git SHA")
        if self.generation_modes != ("sample", "propose"):
            raise ValueError("Tree of Thoughts generation modes drifted")
        if self.evaluation_modes != ("vote", "value"):
            raise ValueError("Tree of Thoughts evaluation modes drifted")
        if self.selection_modes != ("sample", "greedy"):
            raise ValueError("Tree of Thoughts selection modes drifted")
        if self.initial_frontier != ("",) or self.duplicate_candidate_value != 0.0:
            raise ValueError("Tree of Thoughts frontier semantics drifted")


TREE_OF_THOUGHTS_REFERENCE_FIDELITY = TreeOfThoughtsReferenceFidelity()


__all__ = [
    "TREE_OF_THOUGHTS_AUDITED_COMMIT",
    "TREE_OF_THOUGHTS_REFERENCE_FIDELITY",
    "TreeOfThoughtsReferenceFidelity",
]
