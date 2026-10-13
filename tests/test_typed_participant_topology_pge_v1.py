from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.structure import relation_id

from noetrium_platform.capabilities.participant.api import (
    PARTICIPANT_COMMUNICATION_RELATION,
    participant_communication,
    participant_coordination_components,
    participant_dependency,
    participant_graph,
    participant_relation,
    participant_roles,
    participant_waves,
)


def test_participant_topology_identity_is_declaration_order_independent() -> None:
    a_to_b = participant_dependency("planner", "critic")
    b_to_c = participant_dependency("critic", "executor")
    first = participant_graph(
        ("critic", "planner", "executor"),
        (a_to_b, b_to_c),
    )
    second = participant_graph(
        ("executor", "planner", "critic"),
        (b_to_c, a_to_b),
    )
    assert participant_roles(first) == ("critic", "executor", "planner")
    assert first.unit_digest == second.unit_digest
    assert first.semantic_digest == second.semantic_digest


def test_dependency_cycles_are_native_scc_coordination_components() -> None:
    topology = participant_graph(
        ("planner", "critic", "executor"),
        (
            participant_dependency("planner", "critic"),
            participant_dependency("critic", "planner"),
            participant_dependency("critic", "executor"),
        ),
    )
    assert participant_coordination_components(topology) == (
        ("critic", "planner"),
        ("executor",),
    )
    assert participant_waves(topology) == (
        ("critic", "planner"),
        ("executor",),
    )


def test_non_dependency_communication_cycles_do_not_constrain_schedule() -> None:
    topology = participant_graph(
        ("agent-a", "agent-b", "judge"),
        (
            participant_communication(("agent-a",), ("agent-b",), channel="debate"),
            participant_communication(("agent-b",), ("agent-a",), channel="debate"),
            participant_communication(("agent-a", "agent-b"), ("judge",), channel="vote"),
        ),
    )
    assert participant_waves(topology) == (("agent-a", "agent-b", "judge"),)


def test_communication_is_native_hyperrelation() -> None:
    relation = participant_communication(
        ("researcher-a", "researcher-b"),
        ("critic", "judge"),
        channel="evidence",
        parameters={"visibility": "team"},
    )
    topology = participant_graph(
        ("researcher-a", "researcher-b", "critic", "judge"),
        (relation,),
    )
    assert relation in topology.relations
    assert relation_id(relation) == PARTICIPANT_COMMUNICATION_RELATION


def test_topology_rejects_unknown_relation_endpoint() -> None:
    relation = participant_dependency("planner", "missing")
    with pytest.raises(ValueError, match="unknown (member|participant)"):
        participant_graph(("planner", "critic"), (relation,))


def test_topology_rejects_duplicate_roles_and_relations() -> None:
    with pytest.raises(ValueError, match="roles must be unique"):
        participant_graph(("planner", "planner"))
    relation = participant_dependency("planner", "critic")
    with pytest.raises(ValueError, match="relations must be unique"):
        participant_graph(("planner", "critic"), (relation, relation))


def test_arbitrary_paper_specific_relation_is_preserved_without_affecting_waves() -> None:
    relation = participant_relation(
        ("planner",),
        ("critic",),
        "paper.custom-consultation",
        parameters={"rounds": 3},
    )
    topology = participant_graph(("planner", "critic"), (relation,))
    assert relation in topology.relations
    assert participant_waves(topology) == (("critic", "planner"),)
