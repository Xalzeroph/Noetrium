from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class LATSNode:
    action: str = ""
    observation: str = ""
    parent: "LATSNode | None" = None
    visits: int = 0
    value: float = 0.0
    reward: float = 0.0
    is_terminal: bool = False
    exhausted: bool = False
    children: list["LATSNode"] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def add_child(self, child: "LATSNode") -> None:
        if not isinstance(child, LATSNode):
            raise TypeError("LATS child must be LATSNode")
        if child.parent is not self:
            raise ValueError("LATS child parent must point to the receiving node")
        self.children.append(child)

    def uct(self) -> float:
        if self.visits == 0:
            return math.inf if self.value >= 0 else self.value
        if self.parent is None:
            raise ValueError("LATS UCT is defined for a child node")
        if self.parent.visits <= 0:
            raise ValueError("LATS visited child requires positive parent visits")
        return self.value / self.visits + math.sqrt(2.0 * math.log(self.parent.visits) / self.visits)


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


def backpropagate(node: LATSNode, value: float) -> None:
    if not isinstance(node, LATSNode):
        raise TypeError("LATS backpropagation requires LATSNode")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("LATS backpropagation value must be numeric")
    current: LATSNode | None = node
    scalar = float(value)
    while current is not None:
        current.visits += 1
        current.value = (current.value * (current.visits - 1) + scalar) / current.visits
        current = current.parent


def best_nonterminal_child(node: LATSNode) -> LATSNode | None:
    if not isinstance(node, LATSNode):
        raise TypeError("LATS selection requires LATSNode")
    candidates = [child for child in node.children if not child.is_terminal]
    return None if not candidates else max(candidates, key=lambda child: child.uct())


def descend_best_nonterminal(root: LATSNode) -> LATSNode | None:
    if not isinstance(root, LATSNode):
        raise TypeError("LATS selection requires LATSNode")
    current: LATSNode | None = root
    while current is not None and current.children:
        current = best_nonterminal_child(current)
    return current


__all__ = [
    "LATSNode", "LatsBranchState", "backpropagate", "backpropagated_mean",
    "best_nonterminal_child", "descend_best_nonterminal", "is_successful_terminal", "uct_score",
]