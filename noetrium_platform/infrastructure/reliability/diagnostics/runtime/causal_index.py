from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import (
    JsonScalar,
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
)

from .causal_contracts import CausalEdge, freeze_causal_attributes




CAUSAL_GRAPH_INDEX_COMPLEXITY = ComplexityContract(
    algorithm_id="diagnostics.causal-index.v2",
    implementation_digest=canonical_digest(
        ("diagnostics.causal-index.v2", "ordered-adjacency-hash-membership")
    ),
    time_upper_bound=ComplexityBound.linear_sum("causal_nodes", "causal_edges"),
    space_upper_bound=ComplexityBound.linear_sum("causal_nodes", "causal_edges"),
    assumptions=(
        "node and edge identities are hashable with expected O(1) dictionary/set membership",
        "edge output order is preserved by adjacency lists while a parallel set owns membership only",
    ),
    time_lower_bound=ComplexityBound.linear_sum("causal_nodes", "causal_edges"),
    space_lower_bound=ComplexityBound.linear_sum("causal_nodes", "causal_edges"),
)

@dataclass(frozen=True, slots=True)
class _CausalNode:
    node_id: str
    kind: str
    attrs: Mapping[str, JsonScalar]


class CausalRecordIndex:
    """Mutable topology builder whose node payloads are frozen at insertion."""

    def __init__(self) -> None:
        self.nodes: dict[str, _CausalNode] = {}
        self.out: dict[str, list[CausalEdge]] = {}
        # Adjacency lists preserve deterministic projection order. Membership
        # is separate so duplicate suppression is O(1) expected rather than a
        # linear scan of a high-degree source on every insertion.
        self._edge_membership: dict[str, set[CausalEdge]] = {}

    def add_node(self, node: _CausalNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: CausalEdge) -> None:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            raise KeyError("causal edge references unknown node")
        members = self._edge_membership.setdefault(edge.source, set())
        if edge in members:
            return
        members.add(edge)
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
        self.add_edge(CausalEdge(source, relation, target))


__all__ = ["CAUSAL_GRAPH_INDEX_COMPLEXITY", "CausalRecordIndex"]
