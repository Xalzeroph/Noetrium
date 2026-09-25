from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonScalar

from .causal_contracts import CausalEdge, freeze_causal_attributes


@dataclass(frozen=True, slots=True)
class _CausalNode:
    node_id: str
    kind: str
    attrs: Mapping[str, JsonScalar]


class CausalGraph:
    """Mutable topology builder whose node payloads are frozen at insertion."""

    def __init__(self) -> None:
        self.nodes: dict[str, _CausalNode] = {}
        self.out: dict[str, list[CausalEdge]] = {}

    def add_node(self, node: _CausalNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: CausalEdge) -> None:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            raise KeyError("causal edge references unknown node")
        self.out.setdefault(edge.source, []).append(edge)

    def ensure_node(self, object_id: str, kind: str, **attrs: JsonScalar) -> None:
        if object_id not in self.nodes:
            self.add_node(
                _CausalNode(
                    object_id,
                    kind,
                    freeze_causal_attributes(attrs),
                )
            )

    def ensure_edge(self, source: str, relation: str, target: str) -> None:
        edge = CausalEdge(source, relation, target)
        if edge not in self.out.get(source, ()):
            self.add_edge(edge)


__all__ = ["CausalGraph"]
