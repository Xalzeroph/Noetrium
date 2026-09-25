from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FailedTrajectory:
    final_answer: str
    trajectory: str

    def __post_init__(self) -> None:
        if not isinstance(self.final_answer, str):
            raise TypeError("LATS failed-trajectory final answer must be a string")
        if not isinstance(self.trajectory, str) or not self.trajectory.strip():
            raise ValueError("LATS failed trajectory text is required")


def unique_failed_trajectories(
    failed: tuple[FailedTrajectory, ...],
    *,
    limit: int = 3,
) -> tuple[FailedTrajectory, ...]:
    """Mirror the audited first-seen unique-final-answer filtering."""

    if type(limit) is not int or limit <= 0:
        raise ValueError("LATS unique failed-trajectory limit must be positive")
    seen: set[str] = set()
    rows: list[FailedTrajectory] = []
    for item in failed:
        if not isinstance(item, FailedTrajectory):
            raise TypeError("LATS failed trajectories must be FailedTrajectory values")
        if item.final_answer in seen:
            continue
        rows.append(item)
        seen.add(item.final_answer)
        if len(rows) >= limit:
            break
    return tuple(rows)


def should_refresh_reflections(*, failed_count: int, reflection_count: int) -> bool:
    """Reproduce the WebShop LATS reflection trigger.

    The audited implementation refreshes reflections when failed trajectories
    outnumber existing reflections while the failed count remains strictly below
    four. That keeps reflection generation bounded to the first three failures.
    """

    if type(failed_count) is not int or failed_count < 0:
        raise ValueError("LATS failed_count must be non-negative")
    if type(reflection_count) is not int or reflection_count < 0:
        raise ValueError("LATS reflection_count must be non-negative")
    return failed_count > reflection_count and failed_count < 4


__all__ = [
    "FailedTrajectory",
    "should_refresh_reflections",
    "unique_failed_trajectories",
]
