from __future__ import annotations
from noetrium_platform.research.execution.graph.api.contracts import execution_vertex_id

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

from noetrium_platform.composition.research_graph_frontier import (
    ResearchGraphDependencyFrontier,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphFailureProvenance,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
)


def _node(node_id: str, *dependencies: str) -> ResearchSchedulingNode:
    return ResearchSchedulingNode(
        node_id,
        canonical_digest({"node": node_id}),
        tuple(dependencies),
    )


def _success(node: ResearchSchedulingNode) -> ResearchGraphNodeResult:
    return ResearchGraphNodeResult(
        execution_vertex_id(node),
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
    plan = ResearchSchedulingPlan(
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
        assert frontier.ready_node_ids(pending) == (execution_vertex_id(node),)
        frontier.consume_ready(execution_vertex_id(node))
        pending.remove(execution_vertex_id(node))
        frontier.record_terminal(_success(node))
        if index + 1 < len(nodes):
            assert frontier.ready_node_ids(pending) == (execution_vertex_id(nodes[index + 1]),)

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
    plan = ResearchSchedulingPlan(
        "frontier-failure",
        canonical_digest({"revision": "frontier-failure"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=tuple(execution_vertex_id(node) for node in nodes),
        terminal_results={},
    )
    pending = {execution_vertex_id(node) for node in nodes}

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
    plan = ResearchSchedulingPlan(
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


def test_terminal_update_never_rescans_high_fanin_target_incoming_relations() -> None:
    sources = tuple(f"source-{index:03d}" for index in range(64))
    nodes = tuple(_node(node_id) for node_id in sources) + (
        _node("target", *sources),
    )
    plan = ResearchSchedulingPlan(
        "frontier-high-fanin-incremental",
        canonical_digest({"revision": "frontier-high-fanin-incremental"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=tuple(execution_vertex_id(node) for node in nodes),
        terminal_results={},
    )
    pending = set(sources) | {"target"}

    # Initialization is allowed to inspect every incoming relation once.
    # Runtime terminal updates must thereafter use maintained relation/node
    # counters only. Any accidental incoming rescan will fail immediately.
    frontier._incoming["target"] = object()  # type: ignore[assignment]

    for node in nodes[:-1]:
        frontier.consume_ready(execution_vertex_id(node))
        pending.remove(execution_vertex_id(node))
        frontier.record_terminal(_success(node))

    assert frontier.ready_node_ids(pending) == ("target",)


def test_frontier_bounded_ready_rotation_avoids_wide_frontier_sorting_and_hol() -> None:
    nodes = tuple(_node(node_id) for node_id in ("a", "b", "c", "d"))
    plan = ResearchSchedulingPlan(
        "frontier-bounded-rotation",
        canonical_digest({"revision": "frontier-bounded-rotation"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=tuple(execution_vertex_id(node) for node in nodes),
        terminal_results={},
    )
    pending = {execution_vertex_id(node) for node in nodes}

    assert frontier.next_ready_node_ids(pending, limit=2) == ("a", "b")
    assert frontier.next_ready_node_ids(pending, limit=2) == ("c", "d")
    assert frontier.next_ready_node_ids(pending, limit=2) == ("a", "b")
    assert frontier.ready_node_ids(pending) == ("a", "b", "c", "d")


def test_frontier_ready_rotation_removes_consumed_nodes_in_constant_time() -> None:
    nodes = tuple(_node(node_id) for node_id in ("a", "b", "c"))
    plan = ResearchSchedulingPlan(
        "frontier-ready-consume",
        canonical_digest({"revision": "frontier-ready-consume"}),
        nodes,
    )
    frontier = ResearchGraphDependencyFrontier(
        plan,
        selected_node_ids=tuple(execution_vertex_id(node) for node in nodes),
        terminal_results={},
    )
    pending = {execution_vertex_id(node) for node in nodes}

    assert frontier.next_ready_node_ids(pending, limit=1) == ("a",)
    frontier.consume_ready("a")
    pending.remove("a")
    assert frontier.next_ready_node_ids(pending, limit=2) == ("b", "c")
    frontier.restore_ready("a")
    pending.add("a")
    assert frontier.next_ready_node_ids(pending, limit=3) == ("b", "c", "a")
