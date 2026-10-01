from components.reference.single_agent.memory import (
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


def test_retire_preserves_public_typed_node_metadata() -> None:
    node = MemoryNodeRecord(
        "memory:typed",
        "state",
        "typed",
        "typed-content",
        "g0",
        purpose="semantic responsibility",
        scope="minecraft",
        mode="CURRENT",
        schema={"kind": "object"},
        access=("MEMORY_ASK", "EXACT"),
        sources=("evidence:seed",),
        transform={"operator": "PROJECT"},
        maintenance_contract={"refresh": "on_receipt"},
        provenance={"source": "verified"},
    )
    graph = VersionedMemoryGraph(MemoryGraphSnapshot("g0", (node,), ()))
    transaction = graph.stage(
        (MemoryGraphOperation("retire_node", "memory:typed"),),
        rationale_digest="retire-preserve-metadata",
    )
    graph.activate(transaction)
    retired = graph.snapshot().node("memory:typed")
    assert retired is not None
    assert not retired.active
    assert retired.purpose == node.purpose
    assert retired.scope == node.scope
    assert retired.mode == node.mode
    assert retired.schema == node.schema
    assert retired.access == node.access
    assert retired.sources == node.sources
    assert retired.transform == node.transform
    assert retired.maintenance_contract == node.maintenance_contract
    assert retired.provenance == node.provenance
