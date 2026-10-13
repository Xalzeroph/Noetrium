"""Exact critical-tail semantics without hyperedge cross-product work."""
from types import SimpleNamespace

from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    execution_flow,
    execution_graph,
    execution_graph_index,
    execution_vertex,
)


class _TargetReadCounter:
    def __init__(self, values):
        self.values = values
        self.reads = {}

    def __getitem__(self, index):
        self.reads[index] = self.reads.get(index, 0) + 1
        return self.values[index]


def test_hyperedge_critical_path_reuses_one_target_reduction():
    sources = tuple(f"source-{i}" for i in range(120))
    targets = tuple(f"target-{i}" for i in range(80))
    vertices = tuple(
        execution_vertex(vertex_id, canonical_digest({"vertex": vertex_id}),
                         static_cost=1 + (index % 17))
        for index, vertex_id in enumerate(sources + targets)
    )
    relation = execution_flow(sources, targets)
    graph = execution_graph(
        "critical-hypergraph", canonical_digest({"revision": 1}),
        vertices, (relation,),
    )
    index = execution_graph_index(graph)
    counter = _TargetReadCounter(index.relation_targets)
    measured_index = SimpleNamespace(
        topological_order=index.topological_order,
        outgoing_relation_indices=index.outgoing_relation_indices,
        relation_targets=counter,
        by_id=index.by_id,
    )
    tails = ResearchGraphScheduler._critical_path_tail_work(measured_index)
    assert len(tails) == len(sources) + len(targets)
    assert all(tails[target] == 0.0 for target in targets)
    max_target_cost = max(
        float(1 + ((len(sources) + i) % 17))
        for i in range(len(targets))
    )
    assert all(tails[source] == max_target_cost for source in sources)
    assert counter.reads == {0: 1}


def test_multiple_hyperedges_preserve_maximal_downstream_path():
    ids = ("a", "b", "c", "d", "e", "f")
    weights = dict(zip(ids, (1, 2, 3, 4, 5, 6)))
    vertices = tuple(
        execution_vertex(x, canonical_digest({"vertex": x}), static_cost=weights[x])
        for x in ids
    )
    graph = execution_graph(
        "multi-hypergraph", canonical_digest({"revision": 2}),
        vertices,
        (execution_flow(("a", "b"), ("c", "d")),
         execution_flow(("c", "d"), ("e", "f"))),
    )
    index = execution_graph_index(graph)
    tails = ResearchGraphScheduler._critical_path_tail_work(index)
    assert tails["e"] == tails["f"] == 0.0
    assert tails["c"] == tails["d"] == 6.0
    assert tails["a"] == tails["b"] == 10.0
