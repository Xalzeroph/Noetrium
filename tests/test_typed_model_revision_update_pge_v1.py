from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelPromotionDecision,
    ModelPromotionDisposition,
    ModelRevisionConflictError,
    ModelRevisionEvidence,
    ModelRevisionEvidenceKind,
    ModelRevisionIdentity,
    ModelRevisionIntegrityError,
    ModelRevisionStateError,
    ModelRevisionCommit,
    ModelUpdateBuildEvidence,
    ModelUpdateBuildReceipt,
    ModelUpdatePlan,
    ModelUpdateProposal,
    PreparedModelRevision,
)
from noetrium_platform.capabilities.model.catalog.revision.providers import SQLiteModelRevisionAuthority
from noetrium_platform.foundation.kernel.kernel import (
    CanonicalDecodingError, CanonicalDecodingFailureKind, ImmutableModelIdentity,
)


def _model(revision: str) -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        logical_name="learner", model_id="learner", revision=revision,
        engine="engine", engine_version="1", dtype="bf16", quantization=None,
        context_length=4096, tokenizer_revision="tok-1",
    )


def _initial() -> ModelRevisionIdentity:
    return ModelRevisionIdentity(_model("r1"), "1" * 64)


def _candidate(initial: ModelRevisionIdentity, revision: str = "r2") -> ModelRevisionIdentity:
    digit = "6" if revision == "r2" else "7"
    return ModelRevisionIdentity(
        _model(revision), digit * 64, parent_revision_digest=initial.digest()
    )


def _plan(initial: ModelRevisionIdentity, plan_id: str = "online-update-1") -> ModelUpdatePlan:
    return ModelUpdatePlan(
        plan_id=plan_id,
        predecessor_revision_digest=initial.digest(),
        update_contract_id="paper.online-learning.v1",
        implementation_digest="2" * 64,
        configuration_digest="3" * 64,
        training_input_digest="4" * 64,
        randomness_digest="5" * 64,
    )


def _proposal(initial: ModelRevisionIdentity, proposal_id: str = "online-update-1") -> ModelUpdateProposal:
    return _plan(initial, proposal_id).to_proposal(
        proposal_id, evidence_refs=("artifact:training-cut",)
    )


def _build(
    initial: ModelRevisionIdentity,
    proposal_id: str = "online-update-1",
    revision: str = "r2",
) -> ModelUpdateBuildReceipt:
    plan = _plan(initial, proposal_id)
    proposal = plan.to_proposal(proposal_id, evidence_refs=("artifact:training-cut",))
    candidate = _candidate(initial, revision)
    evidence = ModelUpdateBuildEvidence(
        plan.digest(), candidate.digest(), "0" * 64, "paper.trainer.build.v1"
    )
    return ModelUpdateBuildReceipt(
        plan, proposal, initial, candidate, "paper.trainer.v1", "f" * 64, (evidence,)
    )


def _evidence(kind: ModelRevisionEvidenceKind, revision: str, digit: str) -> ModelRevisionEvidence:
    return ModelRevisionEvidence(kind, revision, digit * 64, f"paper.evidence.{kind.value}.v1")


def _prepared(initial: ModelRevisionIdentity) -> PreparedModelRevision:
    build = _build(initial)
    return PreparedModelRevision(
        build.proposal, build.predecessor, build.candidate, build.digest(),
        2, "8" * 64, "9" * 64
    )


def _decision(initial: ModelRevisionIdentity, candidate: ModelRevisionIdentity) -> ModelPromotionDecision:
    digest = candidate.digest()
    return ModelPromotionDecision(
        candidate_revision_digest=digest,
        predecessor_active_revision_digest=initial.digest(),
        qualification_evidence=(
            _evidence(ModelRevisionEvidenceKind.QUALIFICATION, digest, "a"),
        ),
        evaluation_evidence=(
            _evidence(ModelRevisionEvidenceKind.EVALUATION, digest, "b"),
        ),
        disposition=ModelPromotionDisposition.PROMOTE,
        reason_digest="c" * 64,
        policy_contract_id="paper.promotion.v1",
        policy_implementation_digest="d" * 64,
        policy_configuration_digest="e" * 64,
    )


def _authority(tmp_path: Path) -> tuple[Path, SQLiteModelRevisionAuthority, ModelRevisionIdentity]:
    path = tmp_path / "model-revisions.sqlite3"
    authority = SQLiteModelRevisionAuthority(path)
    initial = _initial()
    authority.initialize(initial)
    return path, authority, initial


def test_revision_values_are_immutable_and_bind_exact_lineage() -> None:
    initial = _initial()
    prepared = _prepared(initial)
    assert prepared.predecessor_revision_digest == initial.digest()
    assert prepared.candidate.parent_revision_digest == initial.digest()
    with pytest.raises(FrozenInstanceError):
        initial.revision_artifact_digest = "f" * 64  # type: ignore[misc]
    wrong = ModelRevisionIdentity(_model("r2"), "6" * 64, parent_revision_digest="f" * 64)
    with pytest.raises(ValueError, match="exact predecessor"):
        PreparedModelRevision(_proposal(initial), initial, wrong, "0" * 64, 2, "8" * 64, "9" * 64)


def test_commit_and_promotion_evidence_must_bind_exact_candidate() -> None:
    initial = _initial()
    prepared = _prepared(initial)
    wrong = _evidence(ModelRevisionEvidenceKind.VALIDATION, initial.digest(), "a")
    with pytest.raises(ValueError, match="exact model revision"):
        ModelRevisionCommit(prepared, (wrong,), 3)
    candidate = prepared.candidate
    wrong_qualification = _evidence(
        ModelRevisionEvidenceKind.QUALIFICATION, initial.digest(), "b"
    )
    with pytest.raises(ValueError, match="exact model revision"):
        ModelPromotionDecision(
            candidate.digest(), initial.digest(), (wrong_qualification,),
            (_evidence(ModelRevisionEvidenceKind.EVALUATION, candidate.digest(), "c"),),
            ModelPromotionDisposition.PROMOTE, "d" * 64,
            "paper.promotion.v1", "e" * 64, "f" * 64,
        )


def test_promotion_policy_implementation_and_configuration_change_decision_identity() -> None:
    initial = _initial()
    candidate = _candidate(initial)
    a = _decision(initial, candidate)
    b = ModelPromotionDecision(
        a.candidate_revision_digest, a.predecessor_active_revision_digest,
        a.qualification_evidence, a.evaluation_evidence, a.disposition, a.reason_digest,
        a.policy_contract_id, "f" * 64, a.policy_configuration_digest,
    )
    c = ModelPromotionDecision(
        a.candidate_revision_digest, a.predecessor_active_revision_digest,
        a.qualification_evidence, a.evaluation_evidence, a.disposition, a.reason_digest,
        a.policy_contract_id, a.policy_implementation_digest, "f" * 64,
    )
    assert len({a.digest(), b.digest(), c.digest()}) == 3


def test_durable_prepare_allocates_generation_and_reopens_after_crash(tmp_path: Path) -> None:
    path, authority, initial = _authority(tmp_path)
    candidate = _candidate(initial)
    prepared = authority.prepare_successor(
        _build(initial), expected_generation=1,
        recovery_anchor_digest="8" * 64, validation_plan_digest="9" * 64,
    )
    assert prepared.preparation_generation == 2
    assert authority.snapshot().authority_generation == 2
    reopened = SQLiteModelRevisionAuthority(path)
    recovered = reopened.load_prepared(prepared.proposal.digest())
    assert recovered == prepared
    assert recovered.digest() == prepared.digest()


def test_prepare_exact_retry_is_idempotent_but_stale_different_prepare_is_fenced(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    first = authority.prepare_successor(
        _build(initial), expected_generation=1,
        recovery_anchor_digest="8" * 64, validation_plan_digest="9" * 64,
    )
    retry = authority.prepare_successor(
        _build(initial), expected_generation=1,
        recovery_anchor_digest="8" * 64, validation_plan_digest="9" * 64,
    )
    assert retry == first
    with pytest.raises(ModelRevisionConflictError, match="stale"):
        authority.prepare_successor(
            _build(initial, "competing-update", "r3"), expected_generation=1,
            recovery_anchor_digest="a" * 64, validation_plan_digest="b" * 64,
        )


def test_commit_is_durable_idempotent_and_generation_fenced(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared = authority.prepare_successor(
        _build(initial), expected_generation=1,
        recovery_anchor_digest="8" * 64, validation_plan_digest="9" * 64,
    )
    validation = (
        _evidence(ModelRevisionEvidenceKind.VALIDATION, prepared.candidate.digest(), "a"),
    )
    commit = authority.commit_successor(prepared, validation, expected_generation=2)
    assert commit.commit_generation == 3
    assert authority.commit_successor(prepared, validation, expected_generation=2) == commit


def _committed(
    authority: SQLiteModelRevisionAuthority,
    initial: ModelRevisionIdentity,
) -> tuple[PreparedModelRevision, object]:
    prepared = authority.prepare_successor(
        _build(initial), expected_generation=1,
        recovery_anchor_digest="8" * 64, validation_plan_digest="9" * 64,
    )
    validation = (
        _evidence(ModelRevisionEvidenceKind.VALIDATION, prepared.candidate.digest(), "a"),
    )
    commit = authority.commit_successor(prepared, validation, expected_generation=2)
    return prepared, commit


def test_promotion_requires_exact_committed_successor_and_updates_active_generation(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared, _ = _committed(authority, initial)
    decision = _decision(initial, prepared.candidate)
    receipt = authority.promote(decision, expected_generation=3)
    assert receipt.activation_generation == 4
    snapshot = authority.snapshot()
    assert snapshot.authority_generation == 4
    assert snapshot.active_revision == prepared.candidate
    assert authority.promote(decision, expected_generation=3) == receipt


def test_uncommitted_candidate_cannot_be_promoted(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    candidate = _candidate(initial)
    with pytest.raises(ModelRevisionStateError, match="not committed"):
        authority.promote(_decision(initial, candidate), expected_generation=1)


def test_rollback_requires_current_failed_revision_and_committed_ancestor(tmp_path: Path) -> None:
    path, authority, initial = _authority(tmp_path)
    prepared, _ = _committed(authority, initial)
    promoted = authority.promote(_decision(initial, prepared.candidate), expected_generation=3)
    trigger = (
        _evidence(
            ModelRevisionEvidenceKind.ROLLBACK_TRIGGER,
            promoted.active_revision_digest,
            "f",
        ),
    )
    with pytest.raises(ModelRevisionStateError, match="committed ancestor"):
        authority.rollback(
            promoted.active_revision_digest, "0" * 64, trigger,
            recovery_anchor_digest="1" * 64, expected_generation=4,
        )
    receipt = authority.rollback(
        promoted.active_revision_digest, initial.digest(), trigger,
        recovery_anchor_digest="1" * 64, expected_generation=4,
    )
    assert receipt.rollback_generation == 5
    assert SQLiteModelRevisionAuthority(path).snapshot().active_revision == initial
    assert authority.rollback(
        promoted.active_revision_digest, initial.digest(), trigger,
        recovery_anchor_digest="1" * 64, expected_generation=4,
    ) == receipt


def test_stale_rollback_is_fenced(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared, _ = _committed(authority, initial)
    promoted = authority.promote(_decision(initial, prepared.candidate), expected_generation=3)
    trigger = (_evidence(ModelRevisionEvidenceKind.ROLLBACK_TRIGGER, promoted.active_revision_digest, "f"),)
    with pytest.raises(ModelRevisionConflictError, match="stale"):
        authority.rollback(
            promoted.active_revision_digest, initial.digest(), trigger,
            recovery_anchor_digest="1" * 64, expected_generation=3,
        )


def test_corrupt_or_torn_revision_database_fails_closed(tmp_path: Path) -> None:
    torn = tmp_path / "torn.sqlite3"
    torn.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(ModelRevisionIntegrityError):
        SQLiteModelRevisionAuthority(torn)

    path, authority, _ = _authority(tmp_path / "schema")
    connection = authority._connect()  # adversarial corruption fixture
    try:
        connection.execute("DROP TABLE commits")
    finally:
        connection.close()
    with pytest.raises(ModelRevisionIntegrityError, match="table set"):
        SQLiteModelRevisionAuthority(path)


def test_rollback_lineage_cycle_fails_closed(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared, _ = _committed(authority, initial)
    promoted = authority.promote(_decision(initial, prepared.candidate), expected_generation=3)
    connection = authority._connect()  # adversarial corruption fixture
    try:
        connection.execute(
            "UPDATE revisions SET parent_digest=? WHERE digest=?",
            (promoted.active_revision_digest, promoted.active_revision_digest),
        )
    finally:
        connection.close()
    trigger = (_evidence(
        ModelRevisionEvidenceKind.ROLLBACK_TRIGGER, promoted.active_revision_digest, "c"
    ),)
    with pytest.raises(ModelRevisionIntegrityError, match="cycle"):
        authority.rollback(
            promoted.active_revision_digest, initial.digest(), trigger,
            recovery_anchor_digest="1" * 64, expected_generation=4,
        )


def test_rollback_missing_parent_fails_closed(tmp_path: Path) -> None:
    _, authority, initial = _authority(tmp_path)
    prepared, _ = _committed(authority, initial)
    promoted = authority.promote(_decision(initial, prepared.candidate), expected_generation=3)
    connection = authority._connect()  # adversarial corruption fixture
    try:
        connection.execute(
            "UPDATE revisions SET parent_digest=? WHERE digest=?",
            ("f" * 64, promoted.active_revision_digest),
        )
    finally:
        connection.close()
    trigger = (_evidence(
        ModelRevisionEvidenceKind.ROLLBACK_TRIGGER, promoted.active_revision_digest, "d"
    ),)
    with pytest.raises(ModelRevisionIntegrityError, match="missing parent"):
        authority.rollback(
            promoted.active_revision_digest, initial.digest(), trigger,
            recovery_anchor_digest="1" * 64, expected_generation=4,
        )


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
def test_model_revision_payload_uses_shared_strict_json_decoder(
    tmp_path: Path, payload: bytes, kind: CanonicalDecodingFailureKind
) -> None:
    _, authority, initial = _authority(tmp_path)
    connection = authority._connect()  # adversarial durable-payload corruption fixture
    try:
        connection.execute("UPDATE revisions SET payload=? WHERE digest=?", (payload, initial.digest()))
    finally:
        connection.close()
    with pytest.raises(ModelRevisionIntegrityError) as caught:
        authority.snapshot()
    assert isinstance(caught.value.__cause__, CanonicalDecodingError)
    assert caught.value.__cause__.kind is kind
