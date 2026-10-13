from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThoughtCandidate:
    text: str
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("Tree of Thoughts candidate text must be a string")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("Tree of Thoughts candidate value must be numeric")


def assign_duplicate_zero_values(
    candidates: tuple[str, ...],
    evaluated_values: tuple[float, ...],
) -> tuple[ThoughtCandidate, ...]:
    """Mirror the reference's local duplicate suppression for value evaluation."""

    if len(candidates) != len(evaluated_values):
        raise ValueError("Tree of Thoughts candidate/value lengths must agree")
    seen: set[str] = set()
    rows: list[ThoughtCandidate] = []
    for candidate, value in zip(candidates, evaluated_values):
        if not isinstance(candidate, str):
            raise TypeError("Tree of Thoughts candidates must be strings")
        score = 0.0 if candidate in seen else float(value)
        seen.add(candidate)
        rows.append(ThoughtCandidate(candidate, score))
    return tuple(rows)


def greedy_select(candidates: tuple[ThoughtCandidate, ...], *, count: int) -> tuple[ThoughtCandidate, ...]:
    if type(count) is not int or count <= 0:
        raise ValueError("Tree of Thoughts selection count must be positive")
    return tuple(sorted(candidates, key=lambda row: (-row.value, row.text))[:count])


def sampling_probabilities(candidates: tuple[ThoughtCandidate, ...]) -> tuple[float, ...]:
    """Return the reference weighted-sampling distribution without owning RNG policy."""

    if not candidates:
        raise ValueError("Tree of Thoughts sampling requires candidates")
    total = sum(row.value for row in candidates)
    if total <= 0:
        raise ValueError("Tree of Thoughts sample selection requires positive total value")
    if any(row.value < 0 for row in candidates):
        raise ValueError("Tree of Thoughts sample selection rejects negative values")
    return tuple(row.value / total for row in candidates)


@dataclass(frozen=True, slots=True)
class TreeSearchFrontier:
    depth: int
    candidates: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.depth) is not int or self.depth < 0:
            raise ValueError("Tree of Thoughts depth must be non-negative")
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise ValueError("Tree of Thoughts frontier requires candidates")
        if any(not isinstance(value, str) for value in self.candidates):
            raise TypeError("Tree of Thoughts frontier candidates must be strings")

    def advance(self, selected: tuple[ThoughtCandidate, ...]) -> "TreeSearchFrontier":
        if not selected:
            raise ValueError("Tree of Thoughts cannot advance an empty selection")
        return TreeSearchFrontier(self.depth + 1, tuple(row.text for row in selected))


__all__ = [
    "ThoughtCandidate",
    "TreeSearchFrontier",
    "assign_duplicate_zero_values",
    "greedy_select",
    "sampling_probabilities",
]
