from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class LATSNode:
    """Minimal method-owned LATS search node.

    The node intentionally owns only paper semantics: tree structure, visit/value
    statistics, reward and terminal/exhaustion flags. Environment state remains
    provider-owned and is represented outside this node by Noetrium environment
    checkpoints/fork receipts.
    """

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
        """Mirror the audited WebShop LATS UCT rule exactly.

        Reference semantics:
        * unvisited non-negative child -> +inf
        * unvisited negative child -> its negative value
        * otherwise mean value + sqrt(2 * log(parent.visits) / visits)
        """

        if self.visits == 0:
            return math.inf if self.value >= 0 else self.value
        if self.parent is None:
            raise ValueError("LATS UCT is defined for a child node")
        if self.parent.visits <= 0:
            raise ValueError("LATS visited child requires positive parent visits")
        return self.value / self.visits + math.sqrt(
            2.0 * math.log(self.parent.visits) / self.visits
        )


def backpropagate(node: LATSNode, value: float) -> None:
    """Apply the audited running-mean backpropagation through all ancestors."""

    if not isinstance(node, LATSNode):
        raise TypeError("LATS backpropagation requires LATSNode")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("LATS backpropagation value must be numeric")
    current: LATSNode | None = node
    scalar = float(value)
    while current is not None:
        current.visits += 1
        current.value = (
            current.value * (current.visits - 1) + scalar
        ) / current.visits
        current = current.parent


def best_nonterminal_child(node: LATSNode) -> LATSNode | None:
    """Deterministic UCT argmax without introducing a platform RNG policy."""

    if not isinstance(node, LATSNode):
        raise TypeError("LATS selection requires LATSNode")
    candidates = [child for child in node.children if not child.is_terminal]
    if not candidates:
        return None
    return max(candidates, key=lambda child: child.uct())


def descend_best_nonterminal(root: LATSNode) -> LATSNode | None:
    """Follow UCT-best non-terminal children until a leaf is reached."""

    if not isinstance(root, LATSNode):
        raise TypeError("LATS selection requires LATSNode")
    current: LATSNode | None = root
    while current is not None and current.children:
        current = best_nonterminal_child(current)
    return current


__all__ = [
    "LATSNode",
    "backpropagate",
    "best_nonterminal_child",
    "descend_best_nonterminal",
]
