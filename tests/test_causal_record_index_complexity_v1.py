from __future__ import annotations

from noetrium_platform.infrastructure.reliability.diagnostics.runtime.causal_index import (
    CAUSAL_GRAPH_INDEX_COMPLEXITY,
    CausalRecordIndex,
)


def test_causal_index_deduplicates_with_membership_index_and_preserves_order() -> None:
    graph = CausalRecordIndex()
    graph.ensure_node("root", "failure")
    for index in range(1000):
        graph.ensure_node(f"event-{index}", "event")
        graph.ensure_edge("root", "caused", f"event-{index}")
    for index in range(1000):
        graph.ensure_edge("root", "caused", f"event-{index}")

    assert len(graph.out["root"]) == 1000
    assert len(graph._edge_membership["root"]) == 1000
    assert [edge.target for edge in graph.out["root"][:3]] == [
        "event-0",
        "event-1",
        "event-2",
    ]
    assert graph.out["root"][-1].target == "event-999"


def test_causal_index_complexity_contract_is_tight_linear() -> None:
    contract = CAUSAL_GRAPH_INDEX_COMPLEXITY
    assert contract.time_upper_bound == contract.time_lower_bound
    assert contract.space_upper_bound == contract.space_lower_bound
    assert set(contract.time_upper_bound.variables) == {
        "causal_nodes",
        "causal_edges",
    }
