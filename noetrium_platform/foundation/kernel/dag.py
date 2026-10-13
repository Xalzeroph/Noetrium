"""Canonical finite-DAG algorithms used by every Unit projection."""

from __future__ import annotations

import heapq
from collections import deque
from collections.abc import Hashable
from typing import TypeVar


_NodeT = TypeVar("_NodeT", bound=Hashable)


def deterministic_topological_order(
    nodes: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Return the canonical topological order in Θ(V+E) work.

    Node identifiers are unique strings and determine the stable tie-break among
    simultaneously ready vertices. Duplicate edges are semantically one edge.
    """

    if type(nodes) is not tuple or any(
        type(node) is not str or not node for node in nodes
    ):
        raise TypeError("DAG nodes must be a tuple of non-empty text")
    if len(nodes) != len(set(nodes)):
        raise ValueError("DAG node identities must be unique")
    if type(edges) is not tuple or any(
        type(edge) is not tuple
        or len(edge) != 2
        or any(type(value) is not str or not value for value in edge)
        for edge in edges
    ):
        raise TypeError("DAG edges must be tuple[(text,text), ...]")

    known = set(nodes)
    unique_edges = set(edges)
    for source, target in unique_edges:
        if source not in known or target not in known:
            raise ValueError("DAG edge references unknown node")

    incoming = {node: 0 for node in nodes}
    downstream: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in unique_edges:
        downstream[source].append(target)
        incoming[target] += 1

    ready = [node for node, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        ordered.append(node)
        for target in downstream[node]:
            incoming[target] -= 1
            if incoming[target] == 0:
                heapq.heappush(ready, target)

    if len(ordered) != len(nodes):
        raise ValueError("DAG contains a cycle")
    return tuple(ordered)


def deterministic_hypergraph_topological_order(
    nodes: tuple[_NodeT, ...],
    relations: tuple[
        tuple[tuple[_NodeT, ...], tuple[_NodeT, ...]],
        ...,
    ],
) -> tuple[_NodeT, ...]:
    """Return stable hypergraph order in O(V + R + incidences) work.

    Nodes and relation endpoints must already be in canonical order. Each
    relation is an implicit auxiliary vertex: all sources must be emitted
    before it releases all targets. No source-target edge product is built.
    """
    if type(nodes) is not tuple:
        raise TypeError("DAG nodes must be a tuple")
    try:
        known = set(nodes)
    except TypeError as exc:
        raise TypeError("DAG nodes must be hashable") from exc
    if len(nodes) != len(known):
        raise ValueError("DAG node identities must be unique")
    if type(relations) is not tuple:
        raise TypeError("hypergraph relations must be a tuple")

    outgoing_relation_indices = {node: [] for node in nodes}
    incoming_relation_count = {node: 0 for node in nodes}
    relation_targets = []
    unresolved_sources = []

    for row in relations:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("hypergraph relation must be a pair")
        sources_value, targets_value = row
        if type(sources_value) is not tuple or type(targets_value) is not tuple:
            raise TypeError("hypergraph relation endpoints must be tuples")
        try:
            sources = tuple(dict.fromkeys(sources_value))
            targets = tuple(dict.fromkeys(targets_value))
        except TypeError as exc:
            raise TypeError("hypergraph endpoints must be hashable") from exc
        if any(node not in known for node in sources + targets):
            raise ValueError("hypergraph relation references unknown node")
        if not sources or not targets:
            continue
        relation_index = len(relation_targets)
        relation_targets.append(targets)
        unresolved_sources.append(len(sources))
        for source in sources:
            outgoing_relation_indices[source].append(relation_index)
        for target in targets:
            incoming_relation_count[target] += 1

    ready = deque(
        node for node in nodes if incoming_relation_count[node] == 0
    )
    ordered = []
    while ready:
        node = ready.popleft()
        ordered.append(node)
        for relation_index in outgoing_relation_indices[node]:
            remaining = unresolved_sources[relation_index] - 1
            if remaining < 0:
                raise RuntimeError("hypergraph source counter underflow")
            unresolved_sources[relation_index] = remaining
            if remaining:
                continue
            for target in relation_targets[relation_index]:
                count = incoming_relation_count[target] - 1
                if count < 0:
                    raise RuntimeError("hypergraph target counter underflow")
                incoming_relation_count[target] = count
                if count == 0:
                    ready.append(target)

    if len(ordered) != len(nodes):
        raise ValueError("DAG contains a cycle")
    return tuple(ordered)


def strongly_connected_components(
    nodes: tuple[_NodeT, ...],
    adjacency,
) -> tuple[tuple[_NodeT, ...], ...]:
    """Return SCCs iteratively in O(V + E) time and space."""
    if type(nodes) is not tuple:
        raise TypeError("SCC nodes must be a tuple")
    try:
        known = set(nodes)
    except TypeError as exc:
        raise TypeError("SCC nodes must be hashable") from exc
    if len(known) != len(nodes):
        raise ValueError("SCC node identities must be unique")

    graph = {}
    reverse = {node: [] for node in nodes}
    for node in nodes:
        try:
            targets = tuple(dict.fromkeys(adjacency.get(node, ())))
        except TypeError as exc:
            raise TypeError("SCC adjacency targets must be hashable") from exc
        if any(target not in known for target in targets):
            raise ValueError("SCC adjacency references unknown node")
        graph[node] = targets
        for target in targets:
            reverse[target].append(node)

    visited = set()
    finish = []
    for root in nodes:
        if root in visited:
            continue
        visited.add(root)
        pending = [(root, 0)]
        while pending:
            node, offset = pending[-1]
            targets = graph[node]
            if offset < len(targets):
                target = targets[offset]
                pending[-1] = (node, offset + 1)
                if target not in visited:
                    visited.add(target)
                    pending.append((target, 0))
                continue
            finish.append(node)
            pending.pop()

    assigned = set()
    components = []
    for root in reversed(finish):
        if root in assigned:
            continue
        component = []
        pending = [root]
        assigned.add(root)
        while pending:
            node = pending.pop()
            component.append(node)
            for source in reverse[node]:
                if source not in assigned:
                    assigned.add(source)
                    pending.append(source)
        components.append(tuple(component))
    return tuple(components)


__all__ = ["deterministic_hypergraph_topological_order", "deterministic_topological_order", "strongly_connected_components"]
