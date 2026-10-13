"""Full ready scans do not mutate the incremental frontier."""
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    execution_vertex, execution_graph,
)
from noetrium_platform.composition.research_graph_frontier import (
    ResearchGraphDependencyFrontier,
)


def test_full_ready_window_preserves_order_and_filters_pending_subsets():
    names = tuple(f"node-{i:03d}" for i in range(96))
    digest = canonical_digest({"graph": "ordered-frontier"})
    graph = execution_graph(
        "ready-order", digest,
        tuple(execution_vertex(name, canonical_digest({"node": name})) for name in names),
        (),
    )
    frontier = ResearchGraphDependencyFrontier(
        graph, selected_node_ids=names, terminal_results={},
    )
    all_pending = set(names)
    initial = frontier.next_ready_node_ids(all_pending, limit=len(names))
    assert initial == names
    assert frontier.next_ready_node_ids(all_pending, limit=len(names)) == initial
    subset = set(names[::3])
    assert frontier.next_ready_node_ids(subset, limit=len(names)) == names[::3]
    assert frontier.next_ready_node_ids(all_pending, limit=len(names)) == names

    first = frontier.next_ready_node_ids(all_pending, limit=7)
    assert first == names[:7]
    assert frontier.next_ready_node_ids(all_pending, limit=len(names)) == names[7:] + names[:7]



def test_unadmitted_cancelled_ready_node_is_retired_from_frontier():
    from noetrium_platform.research.execution.graph.api import (
        ResearchGraphNodeResult, ResearchGraphNodeState,
    )
    names = ("a", "b", "c")
    digests = {name: canonical_digest({"node": name}) for name in names}
    graph = execution_graph(
        "cancel-before-admit", canonical_digest({"revision": 3}),
        tuple(execution_vertex(name, digests[name]) for name in names),
        (),
    )
    frontier = ResearchGraphDependencyFrontier(
        graph, selected_node_ids=names, terminal_results={},
    )
    frontier.record_terminal(
        ResearchGraphNodeResult("b", digests["b"], ResearchGraphNodeState.CANCELLED)
    )
    # Even an out-of-date caller-provided pending set must never resurrect
    # an already-terminal Unit.
    assert frontier.next_ready_node_ids(set(names), limit=len(names)) == ("a", "c")
    assert frontier.ready_node_ids(set(names)) == ("a", "c")
