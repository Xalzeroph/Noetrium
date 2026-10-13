from __future__ import annotations

from components.reference.single_agent.memory import (
    MemoryGraphOperation,
    VersionedMemoryGraph,
)


def test_public_memory_graph_preserves_selector_across_lifecycle() -> None:
    graph = VersionedMemoryGraph()
    create = graph.stage(
        (
            MemoryGraphOperation(
                "create_node",
                "memory:partitioned",
                {
                    "kind": "semantic",
                    "label": "partitioned",
                    "content": "partitioned memory",
                    "purpose": "partition one record population",
                    "selector": {"field": "entity_kind", "op": "IN", "value": ["ZOMBIE"]},
                },
            ),
        ),
        rationale_digest="create-selector",
    )
    graph.activate(create)
    created = graph.snapshot().node("memory:partitioned")
    assert created is not None
    assert created.selector == {
        "field": "entity_kind",
        "op": "IN",
        "value": ["ZOMBIE"],
    }

    update = graph.stage(
        (
            MemoryGraphOperation(
                "update_node",
                "memory:partitioned",
                {"selector": {"not": {"field": "entity_kind", "op": "IN", "value": ["ZOMBIE"]}}},
            ),
        ),
        rationale_digest="update-selector",
    )
    graph.activate(update)
    updated = graph.snapshot().node("memory:partitioned")
    assert updated is not None
    assert updated.selector == {
        "not": {"field": "entity_kind", "op": "IN", "value": ["ZOMBIE"]}
    }

    retire = graph.stage(
        (MemoryGraphOperation("retire_node", "memory:partitioned"),),
        rationale_digest="retire-selector",
    )
    graph.activate(retire)
    retired = graph.snapshot().node("memory:partitioned")
    assert retired is not None
    assert not retired.active
    assert retired.selector == updated.selector
