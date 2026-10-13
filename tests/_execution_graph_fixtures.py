from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.execution.graph.api import (
    EXECUTION_VERTEX_SCHEMA,
    execution_flow,
    execution_vertex,
    execution_graph,
    execution_graph_index,
)


def scheduling_vertex(
    node_id: str,
    semantic_digest: str,
    dependencies: tuple[str, ...] = (),
    *,
    effectful: bool = False,
    static_cost: int = 1,
) -> NoetriumUnit:
    deps = tuple(sorted(dependencies))
    vertex = execution_vertex(
        node_id,
        semantic_digest,
        source_path=(node_id,),
        effectful=effectful,
        static_cost=static_cost,
    )
    attributes = {
        **dict(vertex.attributes),
        "test_dependencies": deps,
    }
    return NoetriumUnit(
        unit_id=f"execution-vertex:{canonical_digest(attributes)}",
        schemas=(EXECUTION_VERTEX_SCHEMA,),
        attributes=attributes,
    )


def scheduling_graph(
    graph_id: str,
    revision_digest: str,
    nodes: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    flows = tuple(
        execution_flow(dependency, str(node.attributes["node_id"]))
        for node in nodes
        for dependency in tuple(node.attributes.get("test_dependencies", ()))
    )
    return execution_graph(graph_id, revision_digest, nodes, flows)


def materialize_execution(store, execution_id: str, plan: NoetriumUnit):
    """Test fixture: explicitly materialize the complete immutable plan."""
    store.ensure_execution_identity(execution_id, plan)
    node_ids = tuple(execution_graph_index(plan).by_id)
    if node_ids:
        store.materialize_nodes(execution_id, plan, node_ids)
    return store.snapshot(execution_id)
