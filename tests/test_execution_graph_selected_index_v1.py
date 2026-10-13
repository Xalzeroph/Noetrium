from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.structure import (
    GraphTrigger,
    GraphTriggerKind,
)
from noetrium_platform.research.execution.graph.api import (
    execution_dependency_source_node_ids,
    execution_dependency_target_node_ids,
    execution_dependency_trigger,
    execution_flow,
    execution_graph,
    execution_graph_index,
    execution_vertex,
    execution_vertex_dependents,
    execution_vertex_id,
)


def _d(value: str) -> str:
    return canonical_digest({"value": value})


def test_selected_execution_index_uses_cached_full_index_not_projection_rescan(
    monkeypatch,
) -> None:
    node_ids = tuple(f"node-{index:04d}" for index in range(512))
    vertices = tuple(execution_vertex(node_id, _d(node_id)) for node_id in node_ids)
    flows = tuple(
        execution_flow(node_ids[index - 1], node_ids[index])
        for index in range(1, len(node_ids))
    )
    plan = execution_graph(
        "selected-index",
        _d("revision"),
        vertices,
        flows,
    )

    full = execution_graph_index(plan)
    assert len(full.nodes) == 512
    assert len(full.relations) == 511

    from noetrium_platform.research.execution.graph.api import contracts as graph_contracts

    original_vertices = graph_contracts.execution_graph_vertices
    original_relations = graph_contracts.execution_graph_relations

    def guarded_vertices(candidate):
        if candidate is plan:
            raise AssertionError("selected execution index rescanned full projection vertices")
        return original_vertices(candidate)

    def guarded_relations(candidate):
        if candidate is plan:
            raise AssertionError("selected execution index rescanned full projection relations")
        return original_relations(candidate)

    # The original immutable Unit-derived full index is already cached.
    # Targeted indexing may build its selected subgraph, but must not rescan
    # the original projection.
    monkeypatch.setattr(graph_contracts, "execution_graph_vertices", guarded_vertices)
    monkeypatch.setattr(graph_contracts, "execution_graph_relations", guarded_relations)

    selected = node_ids[:16]
    index = execution_graph_index(plan, selected)
    assert tuple(execution_vertex_id(row) for row in index.nodes) == selected
    assert len(index.relations) == 15
    assert index.topological_order == selected



def test_selected_index_preserves_tight_linear_contract_on_wide_dag() -> None:
    from noetrium_platform.research.execution.graph.api.contracts import (
        SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY,
    )

    root = execution_vertex("root", _d("root"))
    leaves = tuple(
        execution_vertex(f"leaf-{index:04d}", _d(f"leaf-{index:04d}"))
        for index in range(1024)
    )
    plan = execution_graph(
        "wide-selected-index",
        _d("wide-revision"),
        (root, *leaves),
        tuple(execution_flow("root", execution_vertex_id(leaf)) for leaf in leaves),
    )
    selected = ("root", *(execution_vertex_id(leaf) for leaf in leaves))
    full = execution_graph_index(plan)
    index = execution_graph_index(plan, selected)

    assert index.topological_order == full.topological_order
    expected = {execution_vertex_id(leaf) for leaf in leaves}
    assert set(execution_vertex_dependents(plan, "root")) == expected
    contract = SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY
    assert contract.time_upper_bound == contract.time_lower_bound
    assert contract.space_upper_bound == contract.space_lower_bound


def test_selected_index_projects_multi_target_hyperedge_without_leaking_targets() -> None:
    sources = ("s0", "s1", "s2")
    targets = ("t0", "t1", "t2")
    vertices = tuple(
        execution_vertex(node_id, _d(node_id))
        for node_id in (*sources, *targets)
    )
    relation = execution_flow(
        sources,
        targets,
        trigger=GraphTrigger(GraphTriggerKind.QUORUM, 2),
    )
    plan = execution_graph(
        "selected-hyperedge",
        _d("selected-hyperedge-revision"),
        vertices,
        (relation,),
    )

    index = execution_graph_index(plan, ("t1",))

    assert set(index.by_id) == {*sources, "t1"}
    assert len(index.relations) == 1
    projected = index.relations[0]
    assert execution_dependency_source_node_ids(projected) == sources
    assert execution_dependency_target_node_ids(projected) == ("t1",)
    trigger = execution_dependency_trigger(projected)
    assert trigger.kind is GraphTriggerKind.QUORUM
    assert trigger.quorum == 2
