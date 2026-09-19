from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.participant.api import (
    ArchitectureChangeKind,
    ParticipantArchitectureChange,
    ParticipantArchitectureComponent,
    ParticipantArchitectureRevision,
    ParticipantArchitectureTransition,
    ParticipantRevisionConflictError,
    ParticipantRevisionEvidence,
    ParticipantRevisionEvidenceKind,
    ParticipantRevisionIntegrityError,
    ParticipantRevisionProposal,
    ParticipantRevisionStateError,
    ParticipantStateCompatibility,
    ParticipantStateRevision,
    ParticipantStateTransition,
    ParticipantTopology,
    ParticipantTopologyChange,
    ParticipantTopologyMember,
    ParticipantTopologyTransition,
    PreparedParticipantRevision,
    TopologyChangeKind,
)
from noetrium_platform.capabilities.participant.providers import SQLiteParticipantRevisionAuthority
from noetrium_platform.foundation.kernel.kernel import CanonicalDecodingError, CanonicalDecodingFailureKind


def _proposal(predecessor_digest: str, proposal_id: str = "proposal-1") -> ParticipantRevisionProposal:
    return ParticipantRevisionProposal(
        proposal_id, predecessor_digest, "paper.self-update.v1", "1" * 64,
        evidence_refs=("artifact:evaluation-plan",),
    )


def _component(config: str = "3", schema: str = "planner-state.v1") -> ParticipantArchitectureComponent:
    return ParticipantArchitectureComponent(
        "planner", "planner", "2" * 64, config * 64, state_schema_id=schema
    )


def _architectures() -> tuple[
    ParticipantArchitectureRevision,
    ParticipantArchitectureRevision,
    ParticipantArchitectureTransition,
]:
    before = ParticipantArchitectureRevision("agent-a", "arch-1", (_component("3"),))
    after_component = _component("4")
    after = ParticipantArchitectureRevision(
        "agent-a", "arch-2", (after_component,), predecessor_digest=before.digest()
    )
    change = ParticipantArchitectureChange(
        ArchitectureChangeKind.RECONFIGURE_COMPONENT,
        "planner", before.components[0].digest(), after_component.digest(),
    )
    transition = ParticipantArchitectureTransition(
        "arch-transition-1", "agent-a", before.digest(), after.digest(), (change,)
    )
    return before, after, transition


def _topologies() -> tuple[
    ParticipantTopology,
    ParticipantTopology,
    ParticipantTopologyTransition,
]:
    arch, _, _ = _architectures()
    before_member = ParticipantTopologyMember(
        "agent-a", "planner", "5" * 64, "6" * 64, arch.digest()
    )
    before = ParticipantTopology("team", (before_member,))
    after_member = ParticipantTopologyMember(
        "agent-a", "planner", "5" * 64, "7" * 64, arch.digest()
    )
    after = ParticipantTopology("team", (after_member,), 2, before.digest())
    change = ParticipantTopologyChange(
        TopologyChangeKind.REBIND_MEMBER,
        "agent-a", before_member.digest(), after_member.digest(),
    )
    transition = ParticipantTopologyTransition(
        "topology-transition-1", before.digest(), after.digest(), (change,)
    )
    return before, after, transition


def _compat(schema: str = "8", codec: str = "9") -> ParticipantStateCompatibility:
    return ParticipantStateCompatibility(
        "paper.memory-state.v1", schema * 64, "paper.memory-codec.v1", codec * 64
    )


def _states(
    *, compatibility_change: bool = False,
) -> tuple[ParticipantStateRevision, ParticipantStateRevision, ParticipantRevisionProposal, ParticipantStateTransition]:
    before = ParticipantStateRevision(
        "agent-a", "state-1", _compat(), "2" * 64, "3" * 64, "4" * 64
    )
    compatibility = _compat("a", "b") if compatibility_change else _compat()
    after = ParticipantStateRevision(
        "agent-a", "state-2", compatibility, "2" * 64, "5" * 64, "6" * 64,
        predecessor_digest=before.digest(),
    )
    adapter = "7" * 64 if compatibility_change else None
    proposal = ParticipantRevisionProposal(
        "proposal-state", before.digest(), "paper.online-memory-update.v1", "c" * 64,
        migration_adapter_digest=adapter,
    )
    transition = ParticipantStateTransition(
        "state-transition", before.digest(), after.digest(), proposal.update_contract_id,
        migration_adapter_digest=adapter,
    )
    return before, after, proposal, transition


def _validation(revision_digest: str, digit: str = "d") -> ParticipantRevisionEvidence:
    return ParticipantRevisionEvidence(
        ParticipantRevisionEvidenceKind.VALIDATION,
        revision_digest,
        digit * 64,
        "paper.participant-validation.v1",
    )


def test_change_lists_must_reconstruct_exact_topology_candidate() -> None:
    before, after, transition = _topologies()
    wrong_change = ParticipantTopologyChange(
        TopologyChangeKind.REBIND_MEMBER,
        "agent-a", before.members[0].digest(), "f" * 64,
    )
    wrong = ParticipantTopologyTransition(
        transition.transition_id, before.digest(), after.digest(), (wrong_change,)
    )
    with pytest.raises(ValueError, match="source/target member"):
        PreparedParticipantRevision(
            _proposal(before.digest()), before, after, wrong, 2, "8" * 64, "9" * 64
        )


def test_change_lists_must_reconstruct_exact_architecture_candidate() -> None:
    before, after, transition = _architectures()
    wrong_change = ParticipantArchitectureChange(
        ArchitectureChangeKind.RECONFIGURE_COMPONENT,
        "planner", before.components[0].digest(), "f" * 64,
    )
    wrong = ParticipantArchitectureTransition(
        transition.transition_id, "agent-a", before.digest(), after.digest(), (wrong_change,)
    )
    with pytest.raises(ValueError, match="source/target component"):
        PreparedParticipantRevision(
            _proposal(before.digest()), before, after, wrong, 2, "8" * 64, "9" * 64
        )


def test_checkpoint_compatibility_is_independent_from_total_revision_identity() -> None:
    before, after, _ = _architectures()
    assert before.digest() != after.digest()
    assert before.checkpoint_compatibility_digest() == after.checkpoint_compatibility_digest()
    before.require_resume_compatible(after.checkpoint_compatibility_digest())

    state_before, state_after, _, _ = _states()
    assert state_before.digest() != state_after.digest()
    assert state_before.checkpoint_compatibility_digest() == state_after.checkpoint_compatibility_digest()
    state_before.require_resume_compatible(state_after.checkpoint_compatibility_digest())


def test_state_compatibility_change_requires_migration_adapter() -> None:
    before, after, proposal, _ = _states(compatibility_change=True)
    no_adapter_proposal = ParticipantRevisionProposal(
        proposal.proposal_id, proposal.predecessor_revision_digest,
        proposal.update_contract_id, proposal.reason_digest,
    )
    transition = ParticipantStateTransition(
        "state-transition", before.digest(), after.digest(), proposal.update_contract_id
    )
    with pytest.raises(ValueError, match="requires migration adapter"):
        PreparedParticipantRevision(
            no_adapter_proposal, before, after, transition, 2, "8" * 64, "9" * 64
        )


def test_validation_evidence_must_bind_exact_candidate() -> None:
    before, after, transition = _topologies()
    prepared = PreparedParticipantRevision(
        _proposal(before.digest()), before, after, transition, 2, "8" * 64, "9" * 64
    )
    with pytest.raises(ValueError, match="exact candidate"):
        from noetrium_platform.capabilities.participant.api import ParticipantRevisionCommit
        ParticipantRevisionCommit(prepared, (_validation(before.digest()),), 3)


def _authority(
    tmp_path: Path,
) -> tuple[Path, SQLiteParticipantRevisionAuthority, ParticipantTopology]:
    path = tmp_path / "participant-revisions.sqlite3"
    authority = SQLiteParticipantRevisionAuthority(path)
    initial, _, _ = _topologies()
    authority.initialize(initial)
    return path, authority, initial


def _prepare_topology(
    authority: SQLiteParticipantRevisionAuthority,
    initial: ParticipantTopology,
    *,
    expected_generation: int = 1,
) -> PreparedParticipantRevision:
    before, after, transition = _topologies()
    assert before == initial
    return authority.prepare_successor(
        _proposal(initial.digest()), initial, after, transition,
        expected_generation=expected_generation,
        recovery_anchor_digest="8" * 64,
        validation_plan_digest="9" * 64,
    )


def test_durable_prepare_reopens_and_exact_retry_is_idempotent(tmp_path: Path) -> None:
    path, authority, initial = _authority(tmp_path)
    prepared = _prepare_topology(authority, initial)
    assert prepared.preparation_generation == 2
    retry = _prepare_topology(authority, initial)
    assert retry == prepared
    reopened = SQLiteParticipantRevisionAuthority(path)
    assert reopened.load_prepared(prepared.proposal.digest()) == prepared
    assert reopened.snapshot().authority_generation == 2


def test_independent_authority_instance_fences_stale_prepare(tmp_path: Path) -> None:
    path, first, initial = _authority(tmp_path)
    second = SQLiteParticipantRevisionAuthority(path)
    _prepare_topology(first, initial)
    before, after, transition = _architectures()
    # The second authority has a stale generation even if its Python object was opened first.
    with pytest.raises(ParticipantRevisionConflictError, match="stale"):
        second.prepare_successor(
            _proposal(initial.digest(), "competing"), initial,
            ParticipantTopology(
                "team",
                (
                    ParticipantTopologyMember(
                        "agent-a", "planner", "5" * 64, "e" * 64, before.digest()
                    ),
                ),
                2,
                initial.digest(),
            ),
            ParticipantTopologyTransition(
                "competing-transition", initial.digest(),
                ParticipantTopology(
                    "team",
                    (
                        ParticipantTopologyMember(
                            "agent-a", "planner", "5" * 64, "e" * 64, before.digest()
                        ),
                    ),
                    2,
                    initial.digest(),
                ).digest(),
                (
                    ParticipantTopologyChange(
                        TopologyChangeKind.REBIND_MEMBER,
                        "agent-a", initial.members[0].digest(),
                        ParticipantTopologyMember(
                            "agent-a", "planner", "5" * 64, "e" * 64, before.digest()
                        ).digest(),
                    ),
                ),
            ),
            expected_generation=1,
            recovery_anchor_digest="a" * 64,
            validation_plan_digest="b" * 64,
        )


def test_commit_switches_current_revision_and_is_idempotent(tmp_path: Path) -> None:
    path, authority, initial = _authority(tmp_path)
    prepared = _prepare_topology(authority, initial)
    evidence = (_validation(prepared.candidate.digest()),)
    commit = authority.commit_successor(prepared, evidence, expected_generation=2)
    assert commit.commit_generation == 3
    snapshot = SQLiteParticipantRevisionAuthority(path).snapshot()
    assert snapshot.authority_generation == 3
    assert snapshot.current_revision == prepared.candidate
    assert authority.commit_successor(prepared, evidence, expected_generation=2) == commit


def test_stale_commit_is_fenced(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared = _prepare_topology(authority, initial)
    with pytest.raises(ParticipantRevisionConflictError, match="stale"):
        authority.commit_successor(
            prepared, (_validation(prepared.candidate.digest()),), expected_generation=1
        )


def test_corrupt_or_schema_drift_database_fails_closed(tmp_path: Path) -> None:
    torn = tmp_path / "torn.sqlite3"
    torn.write_bytes(b"not-sqlite")
    with pytest.raises(ParticipantRevisionIntegrityError):
        SQLiteParticipantRevisionAuthority(torn)

    path, _, _ = _authority(tmp_path / "schema")
    import sqlite3
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE commits")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ParticipantRevisionIntegrityError, match="table set"):
        SQLiteParticipantRevisionAuthority(path)


@pytest.mark.parametrize(
    ("payload", "kind"),
    (
        (b'{"x":1,"x":2}', CanonicalDecodingFailureKind.DUPLICATE_KEY),
        (b'{"x":NaN}', CanonicalDecodingFailureKind.NON_FINITE),
        (b'\xef\xbb\xbf{"x":1}', CanonicalDecodingFailureKind.BOM),
        (b'{"x":"\\ud800"}', CanonicalDecodingFailureKind.DOMAIN),
        (b'{"x":' + b'[' * 130 + b'0' + b']' * 130 + b'}', CanonicalDecodingFailureKind.DOMAIN),
    ),
)
def test_participant_revision_payload_uses_shared_strict_json_decoder(
    tmp_path: Path, payload: bytes, kind: CanonicalDecodingFailureKind
) -> None:
    _, authority, initial = _authority(tmp_path)
    connection = authority._connect()  # adversarial durable-payload corruption fixture
    try:
        connection.execute("UPDATE revisions SET payload=? WHERE digest=?", (payload, initial.digest()))
    finally:
        connection.close()
    with pytest.raises(ParticipantRevisionIntegrityError) as caught:
        authority.snapshot()
    assert isinstance(caught.value.__cause__, CanonicalDecodingError)
    assert caught.value.__cause__.kind is kind
