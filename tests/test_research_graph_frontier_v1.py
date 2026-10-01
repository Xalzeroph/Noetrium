from __future__ import annotations

from noetrium_platform.composition.research_graph_frontier import (
    ResearchGraphDependencyFrontier,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphFailureProvenance,
    ResearchGraphNode,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphPlan,
)


def _node(node_id: str, *dependencies: str) -> ResearchGraphNode:
    return ResearchGraphNode(
        node_id,
        canonical_digest({"node": node_id}),
        tuple(dependencies),
    )


def _success(node: ResearchGraphNode) -> ResearchGraphNodeResult:
    return ResearchGraphNodeResult(
        node.node_id,
        node.semantic_digest,
        ResearchGraphNodeState.SUCCEEDED,
    )


def test_frontier_advances_1000_node_chain_one_edge_event_at_a_time() -> None:
    node_ids = tuple(f"node-{index:04d}" for index in range(1000))
    nodes = tuple(
        _node(
            node_id,
            *(() if index == 0 else (node_ids[index - 1],)),
        )
        for index, node_id in enumerate(node_ids)
    )
    plan = ResearchGraphPlan(
        "frontier-1000-chain",
        canonical_digest({"revision": "frontier-1000-chain"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=node_ids,
        terminal_results={},
    )
    pending = set(node_ids)

    for index, node in enumerate(nodes):
        assert frontier.blocked_nodes(pending) == ()
        assert frontier.ready_node_ids(pending) == (node.node_id,)
        frontier.consume_ready(node.node_id)
        pending.remove(node.node_id)
        frontier.record_terminal(_success(node))
        if index + 1 < len(nodes):
            assert frontier.ready_node_ids(pending) == (nodes[index + 1].node_id,)

    assert pending == set()
    assert frontier.ready_node_ids(pending) == ()
    assert frontier.blocked_nodes(pending) == ()


def test_frontier_propagates_failure_without_rescanning_unrelated_subgraph() -> None:
    nodes = (
        _node("a"),
        _node("b", "a"),
        _node("c", "b"),
        _node("x"),
        _node("y", "x"),
    )
    plan = ResearchGraphPlan(
        "frontier-failure",
        canonical_digest({"revision": "frontier-failure"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=tuple(node.node_id for node in nodes),
        terminal_results={},
    )
    pending = {node.node_id for node in nodes}

    assert frontier.ready_node_ids(pending) == ("a", "x")
    frontier.consume_ready("a")
    pending.remove("a")
    failed = ResearchGraphNodeResult(
        "a",
        nodes[0].semantic_digest,
        ResearchGraphNodeState.FAILED,
        failure_type="InjectedFailure",
        failure_message="fixture",
        failure_provenance=ResearchGraphFailureProvenance(
            qualified_type="tests.InjectedFailure",
            error_digest=canonical_digest({"failure": "fixture"}),
            safe_message="fixture",
        ),
    )
    frontier.record_terminal(failed)

    blocked = frontier.blocked_nodes(pending)
    assert blocked == (("b", ("a",)),)
    pending.remove("b")
    blocked_b = ResearchGraphNodeResult(
        "b",
        nodes[1].semantic_digest,
        ResearchGraphNodeState.BLOCKED,
        blocked_by_node_ids=("a",),
    )
    frontier.record_terminal(blocked_b)
    assert frontier.blocked_nodes(pending) == (("c", ("b",)),)
    assert frontier.ready_node_ids(pending) == ("x",)


def test_frontier_seeds_from_durable_terminal_results() -> None:
    nodes = (
        _node("a"),
        _node("b", "a"),
        _node("c", "b"),
        _node("x"),
    )
    plan = ResearchGraphPlan(
        "frontier-resume",
        canonical_digest({"revision": "frontier-resume"}),
        nodes,
    )
    existing = {
        "a": _success(nodes[0]),
        "x": _success(nodes[3]),
    }
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=("a", "b", "c", "x"),
        terminal_results=existing,
    )
    assert frontier.ready_node_ids({"b", "c"}) == ("b",)
    frontier.consume_ready("b")
    frontier.record_terminal(_success(nodes[1]))
    assert frontier.ready_node_ids({"c"}) == ("c",)
