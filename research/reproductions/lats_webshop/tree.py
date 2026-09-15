from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class LatsBranchState:
    """Method-owned search metadata referencing OS-owned environment state."""

    node_id: str
    depth: int
    action: str
    observation: str
    environment_checkpoint_ref: str
    reward: float = 0.0
    terminal: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("LATS node_id is required")
        if type(self.depth) is not int or self.depth < 0:
            raise ValueError("LATS branch depth must be non-negative")
        if not isinstance(self.environment_checkpoint_ref, str) or not self.environment_checkpoint_ref.strip():
            raise ValueError("LATS branches require an OS-owned environment checkpoint reference")
        if not isinstance(self.action, str) or not isinstance(self.observation, str):
            raise TypeError("LATS action and observation must be text")


def uct_score(*, value: float, visits: int, parent_visits: int) -> float:
    """Mirror the reference node UCT rule without owning tree persistence."""

    if type(visits) is not int or visits < 0:
        raise ValueError("LATS visits must be non-negative")
    if type(parent_visits) is not int or parent_visits < 0:
        raise ValueError("LATS parent_visits must be non-negative")
    if visits == 0:
        return math.inf if value >= 0 else float(value)
    if parent_visits <= 0:
        raise ValueError("visited LATS nodes require a visited parent")
    return float(value) / visits + math.sqrt(2.0 * math.log(parent_visits) / visits)


def backpropagated_mean(*, current_value: float, visits: int, rollout_value: float) -> tuple[float, int]:
    if type(visits) is not int or visits < 0:
        raise ValueError("LATS visits must be non-negative")
    next_visits = visits + 1
    next_value = (float(current_value) * visits + float(rollout_value)) / next_visits
    return next_value, next_visits


def is_successful_terminal(branch: LatsBranchState) -> bool:
    return branch.terminal and branch.reward == 1.0


__all__ = ["LatsBranchState", "backpropagated_mean", "is_successful_terminal", "uct_score"]
