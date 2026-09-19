from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.api import (
    ArchitectureChangeKind,
    ParticipantArchitectureChange,
    ParticipantArchitectureComponent,
    ParticipantArchitectureRevision,
    ParticipantArchitectureTransition,
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
    ParticipantTopology,
    ParticipantTopologyChange,
    ParticipantTopologyMember,
    ParticipantTopologyTransition,
    TopologyChangeKind,
)


def _d(char: str) -> str:
    return char * 64


def _component(component_id: str, capability: str, char: str) -> ParticipantArchitectureComponent:
    return ParticipantArchitectureComponent(
        component_id=component_id,
        capability_id=capability,
        implementation_digest=_d(char),
        configuration_digest=_d(char.upper().lower()),
    )


def _revision(participant_id: str, char: str) -> ParticipantArchitectureRevision:
    return ParticipantArchitectureRevision(
        participant_id=participant_id,
        revision_id=f"{participant_id}-r1",
        components=(
            ParticipantArchitectureComponent("planner", "planning", _d(char), _d("a")),
            ParticipantArchitectureComponent("memory", "memory", _d("b"), _d("c")),
        ),
    )


def _member(participant_id: str, role: str, char: str) -> ParticipantTopologyMember:
    revision = _revision(participant_id, char)
    return ParticipantTopologyMember(
        participant_id=participant_id,
        role=role,
        requirement_digest=_d(char),
        binding_digest=_d("d"),
        architecture_revision_digest=revision.digest(),
    )


def _topology() -> ParticipantTopology:
    return ParticipantTopology(
        topology_id="triad",
        members=(
            _member("critic", "critic", "1"),
            _member("planner", "planner", "2"),
            _member("executor", "executor", "3"),
        ),
    )


def test_three_participant_topology_identity_is_order_independent() -> None:
    topology = _topology()
    reversed_topology = ParticipantTopology(
        topology_id="triad",
        members=tuple(reversed(topology.members)),
    )
    assert tuple(member.participant_id for member in topology.members) == (
        "critic", "executor", "planner"
    )
    assert topology.digest() == reversed_topology.digest()


def test_dynamic_topology_revision_has_explicit_predecessor_and_transition() -> None:
    before = _topology()
    observer = _member("observer", "observer", "4")
    after = ParticipantTopology(
        topology_id=before.topology_id,
        members=before.members + (observer,),
        revision=2,
        predecessor_digest=before.digest(),
    )
    transition = ParticipantTopologyTransition(
        transition_id="add-observer",
        from_topology_digest=before.digest(),
        to_topology_digest=after.digest(),
        changes=(ParticipantTopologyChange(
            TopologyChangeKind.ADD_MEMBER,
            "observer",
            after_member_digest=observer.digest(),
        ),),
    )
    assert after.digest() != before.digest()
    assert transition.from_topology_digest == before.digest()
    assert transition.to_topology_digest == after.digest()


def test_message_schedule_order_is_distinct_scientific_provenance() -> None:
    topology = _topology()
    first = ParticipantMessageSchedule.for_topology(
        "schedule-a",
        topology,
        (
            ParticipantMessageScheduleEntry("m1", "planner", ("critic",), 0),
            ParticipantMessageScheduleEntry("m2", "critic", ("executor",), 1),
        ),
    )
    second = ParticipantMessageSchedule.for_topology(
        "schedule-b",
        topology,
        (
            ParticipantMessageScheduleEntry("m2", "critic", ("executor",), 0),
            ParticipantMessageScheduleEntry("m1", "planner", ("critic",), 1),
        ),
    )
    assert {entry.message_id for entry in first.entries} == {
        entry.message_id for entry in second.entries
    }
    assert first.digest() != second.digest()


def test_message_schedule_rejects_foreign_or_future_causal_identity() -> None:
    topology = _topology()
    with pytest.raises(ValueError, match="sender"):
        ParticipantMessageSchedule.for_topology(
            "foreign-sender", topology,
            (ParticipantMessageScheduleEntry("m1", "outsider", ("critic",), 0),),
        )
    with pytest.raises(ValueError, match="causal parents"):
        ParticipantMessageSchedule.for_topology(
            "future-parent",
            topology,
            (
                ParticipantMessageScheduleEntry(
                    "m1", "planner", ("critic",), 0, ("m2",)
                ),
                ParticipantMessageScheduleEntry("m2", "critic", ("planner",), 1),
            ),
        )


def test_architecture_revision_and_transition_are_explicit() -> None:
    before = _revision("planner", "5")
    old_planner = next(row for row in before.components if row.component_id == "planner")
    new_planner = ParticipantArchitectureComponent(
        "planner", "planning", _d("6"), _d("7"), "planner-state.v2"
    )
    after = ParticipantArchitectureRevision(
        participant_id="planner",
        revision_id="planner-r2",
        components=(
            new_planner,
            next(row for row in before.components if row.component_id == "memory"),
        ),
        predecessor_digest=before.digest(),
    )
    transition = ParticipantArchitectureTransition(
        "replace-planner", "planner", before.digest(), after.digest(),
        (ParticipantArchitectureChange(
            ArchitectureChangeKind.REPLACE_COMPONENT,
            "planner",
            old_planner.digest(),
            new_planner.digest(),
        ),),
    )
    assert after.digest() != before.digest()
    assert transition.to_revision_digest == after.digest()


def test_resume_uses_explicit_topology_and_architecture_compatibility_facets() -> None:
    topology = _topology()
    revision = _revision("planner", "8")
    topology.require_resume_compatible(topology.checkpoint_compatibility_digest())
    revision.require_resume_compatible(revision.checkpoint_compatibility_digest())
    with pytest.raises(ValueError, match="topology structure"):
        topology.require_resume_compatible(_d("f"))
    with pytest.raises(ValueError, match="state schema"):
        revision.require_resume_compatible(_d("e"))


def test_transitions_reject_noop_or_malformed_changes() -> None:
    topology = _topology()
    with pytest.raises(ValueError, match="must change topology"):
        ParticipantTopologyTransition(
            "noop",
            topology.digest(),
            topology.digest(),
            (ParticipantTopologyChange(
                TopologyChangeKind.REBIND_MEMBER,
                "planner",
                _d("1"),
                _d("2"),
            ),),
        )
    with pytest.raises(ValueError, match="before_member_digest"):
        ParticipantTopologyChange(
            TopologyChangeKind.ADD_MEMBER,
            "observer",
            before_member_digest=_d("1"),
            after_member_digest=_d("2"),
        )
