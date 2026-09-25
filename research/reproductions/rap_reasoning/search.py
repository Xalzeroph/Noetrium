from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RAPReward:
    action_prior: float
    world_state_reward: float
    alpha: float

    def __post_init__(self) -> None:
        for name, value in (
            ("action_prior", self.action_prior),
            ("world_state_reward", self.world_state_reward),
            ("alpha", self.alpha),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"RAP {name} must be finite")
        if not 0.0 <= float(self.alpha) <= 1.0:
            raise ValueError("RAP alpha must be in [0, 1]")

    @property
    def combined(self) -> float:
        r0 = float(self.action_prior)
        r1 = float(self.world_state_reward)
        if r0 < 0.0 or r1 < 0.0:
            return min(r0, r1)
        return r0 ** float(self.alpha) * r1 ** (1.0 - float(self.alpha))


@dataclass(frozen=True, slots=True)
class RAPSimulatedTransition:
    """Method-owned reasoning branch produced by the RAP world model."""

    depth: int
    action: str
    parent_state: str
    predicted_change: str
    predicted_state: str
    reward: RAPReward

    def __post_init__(self) -> None:
        if type(self.depth) is not int or self.depth < 1:
            raise ValueError("RAP transition depth must be positive")
        for name in ("action", "parent_state", "predicted_change", "predicted_state"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"RAP transition {name} is required")
        if not isinstance(self.reward, RAPReward):
            raise TypeError("RAP transition reward must be RAPReward")

    def is_terminal(self, *, max_depth: int) -> bool:
        if type(max_depth) is not int or max_depth < 1:
            raise ValueError("RAP max_depth must be positive")
        return (
            self.reward.world_state_reward > 50.0
            or self.depth >= max_depth
            or self.reward.combined < -1.0
        )


def blocksworld_state_reward(*, satisfied_goals: int, total_goals: int) -> float:
    if type(satisfied_goals) is not int or type(total_goals) is not int:
        raise TypeError("RAP goal counts must be integers")
    if total_goals < 1 or not 0 <= satisfied_goals <= total_goals:
        raise ValueError("RAP goal counts are invalid")
    if satisfied_goals == total_goals:
        return 100.0
    return satisfied_goals / total_goals + 0.5


@dataclass(frozen=True, slots=True)
class RAPBackpropagatedReward:
    cumulative_reward: float
    coefficient: float
    aggregated_reward: float


def backpropagate_mean_rewards(
    node_rewards_leaf_to_root: tuple[float, ...],
    *,
    discount: float = 1.0,
) -> tuple[RAPBackpropagatedReward, ...]:
    """Mirror RAP's reverse-path discounted mean reward aggregation."""

    if not isinstance(node_rewards_leaf_to_root, tuple) or not node_rewards_leaf_to_root:
        raise ValueError("RAP backpropagation requires a non-empty reward tuple")
    if isinstance(discount, bool) or not isinstance(discount, (int, float)) or not math.isfinite(float(discount)):
        raise ValueError("RAP discount must be finite")
    reward = 0.0
    coefficient = 1.0
    rows: list[RAPBackpropagatedReward] = []
    for node_reward in node_rewards_leaf_to_root:
        if isinstance(node_reward, bool) or not isinstance(node_reward, (int, float)) or not math.isfinite(float(node_reward)):
            raise ValueError("RAP node rewards must be finite")
        reward = reward * float(discount) + float(node_reward)
        coefficient = coefficient * float(discount) + 1.0
        rows.append(RAPBackpropagatedReward(reward, coefficient, reward / coefficient))
    return tuple(rows)


__all__ = [
    "RAPBackpropagatedReward",
    "RAPReward",
    "RAPSimulatedTransition",
    "backpropagate_mean_rewards",
    "blocksworld_state_reward",
]
