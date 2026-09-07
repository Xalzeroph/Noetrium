from noetrium.contracts.systems.components import (
    MemoryGraphOperation,
    MemoryGraphSnapshot,
    MemoryNodeRecord,
    VersionedMemoryGraph,
)


def test_public_memory_graph_preserves_typed_node_metadata() -> None:
    graph = VersionedMemoryGraph(
        MemoryGraphSnapshot(
            "g0",
            (
                MemoryNodeRecord(
                    "memory:root",
                    "state",
                    "root",
                    "root",
                    "g0",
                    purpose="world state",
                    scope="minecraft",
                    mode="CURRENT",
                    schema={"kind": "object"},
                    access=("STATE_READ", "MEMORY_ASK"),
                    sources=("evidence:seed",),
                    transform={"operator": "PROJECT", "fields": ["inventory"]},
                    maintenance_contract={"refresh": "on_receipt"},
                    provenance={"source": "verified"},
                ),
            ),
            (),
        )
    )
    transaction = graph.stage(
        (
            MemoryGraphOperation(
                "create_node",
                "memory:derived",
                {
                    "kind": "semantic",
                    "label": "derived",
                    "content": "derived",
                    "parent_ids": (),
                    "purpose": "semantic abstraction",
                    "scope": "minecraft",
                    "mode": "AGGREGATE",
                    "schema": {"kind": "summary"},
                    "access": ("MEMORY_ASK",),
                    "sources": ("evidence:seed",),
                    "transform": {"operator": "GROUP_BY", "fields": ["kind"]},
                    "maintenance_contract": {"refresh": "after_backfill"},
                    "provenance": {"source": "verified"},
                },
            ),
        ),
        evidence_ids=("evidence:seed",),
        rationale_digest="metadata-test",
    )
    graph.activate(transaction)
    node = graph.snapshot().node("memory:derived")
    assert node is not None
    assert node.mode == "AGGREGATE"
    assert node.transform["operator"] == "GROUP_BY"
    assert node.access == ("MEMORY_ASK",)
    assert node.provenance["source"] == "verified"
