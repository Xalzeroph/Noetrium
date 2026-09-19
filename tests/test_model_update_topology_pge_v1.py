from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelRevisionIdentity,
    ModelRevisionIntegrityError,
    ModelUpdateBuildEvidence,
    ModelUpdateBuildReceipt,
    ModelUpdatePlan,
    ModelUpdateProducerPort,
    ModelUpdateSource,
)
from noetrium_platform.capabilities.model.catalog.revision.providers import (
    FunctionalModelUpdateProducer,
    SQLiteModelRevisionAuthority,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _model(revision: str) -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        logical_name="learner", model_id="learner", revision=revision,
        engine="trainer", engine_version="1", dtype="bf16", quantization=None,
        context_length=8192, tokenizer_revision="tok-1",
    )


def _initial() -> ModelRevisionIdentity:
    return ModelRevisionIdentity(_model("r1"), "1" * 64)


def _candidate(initial: ModelRevisionIdentity, revision: str = "r2") -> ModelRevisionIdentity:
    return ModelRevisionIdentity(
        _model(revision), "6" * 64, parent_revision_digest=initial.digest()
    )


def _plan(
    initial: ModelRevisionIdentity,
    *,
    sources: tuple[ModelUpdateSource, ...] = (),
    implementation_digest: str = "2" * 64,
) -> ModelUpdatePlan:
    return ModelUpdatePlan(
        plan_id="paper-update-1",
        predecessor_revision_digest=initial.digest(),
        update_contract_id="paper.distill-or-finetune.v1",
        implementation_digest=implementation_digest,
        configuration_digest="3" * 64,
        training_input_digest="4" * 64,
        randomness_digest="5" * 64,
        source_revisions=sources,
    )


def _producer(
    candidate: ModelRevisionIdentity,
    *,
    implementation_digest: str = "a" * 64,
) -> FunctionalModelUpdateProducer:
    return FunctionalModelUpdateProducer(
        producer_contract_id="paper.model-update-builder.v1",
        implementation_digest=implementation_digest,
        handler=lambda _plan, _predecessor: (candidate, ("b" * 64,)),
    )


def test_update_source_order_is_canonical_but_source_topology_changes_identity() -> None:
    initial = _initial()
    teacher = ModelUpdateSource("teacher", "teacher", "7" * 64)
    merge = ModelUpdateSource("merge-b", "merge-input", "8" * 64)
    left = _plan(initial, sources=(teacher, merge))
    reordered = _plan(initial, sources=(merge, teacher))
    changed = _plan(
        initial,
        sources=(teacher, ModelUpdateSource("merge-c", "merge-input", "9" * 64)),
    )

    assert tuple(source.source_id for source in left.source_revisions) == ("merge-b", "teacher")
    assert left.digest() == reordered.digest()
    assert left.digest() != changed.digest()


def test_update_plan_rejects_duplicate_or_predecessor_source() -> None:
    initial = _initial()
    with pytest.raises(ValueError, match="source ids"):
        _plan(
            initial,
            sources=(
                ModelUpdateSource("teacher", "teacher", "7" * 64),
                ModelUpdateSource("teacher", "reference", "8" * 64),
            ),
        )
    with pytest.raises(ValueError, match="predecessor"):
        _plan(
            initial,
            sources=(ModelUpdateSource("base", "teacher", initial.digest()),),
        )


def test_plan_to_proposal_is_exact_and_drift_is_rejected() -> None:
    initial = _initial()
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1", evidence_refs=("artifact:cut",))
    plan.require_proposal(proposal)
    drifted = _plan(initial, implementation_digest="d" * 64)
    with pytest.raises(ValueError, match="exact update plan"):
        drifted.require_proposal(proposal)


def test_functional_update_producer_returns_exact_build_receipt() -> None:
    initial = _initial()
    candidate = _candidate(initial)
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1")
    producer = _producer(candidate)

    receipt = producer.build_candidate(plan, proposal, initial)

    assert isinstance(producer, ModelUpdateProducerPort)
    assert receipt.plan == plan
    assert receipt.proposal == proposal
    assert receipt.predecessor == initial
    assert receipt.candidate == candidate
    assert receipt.build_evidence[0].plan_digest == plan.digest()
    assert receipt.build_evidence[0].candidate_revision_digest == candidate.digest()


def test_build_receipt_rejects_wrong_candidate_or_evidence_binding() -> None:
    initial = _initial()
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1")
    wrong = ModelRevisionIdentity(_model("r2"), "6" * 64, parent_revision_digest="f" * 64)
    evidence = ModelUpdateBuildEvidence(plan.digest(), wrong.digest(), "b" * 64, "paper.builder.v1")
    with pytest.raises(ValueError, match="exact predecessor"):
        ModelUpdateBuildReceipt(plan, proposal, initial, wrong, "paper.builder.v1", "a" * 64, (evidence,))


def test_build_receipt_identity_binds_producer_implementation() -> None:
    initial = _initial()
    candidate = _candidate(initial)
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1")
    left = _producer(candidate, implementation_digest="a" * 64).build_candidate(
        plan, proposal, initial
    )
    right = _producer(candidate, implementation_digest="c" * 64).build_candidate(
        plan, proposal, initial
    )
    assert left.candidate == right.candidate
    assert left.digest() != right.digest()


def test_durable_prepare_reopens_with_exact_build_receipt_identity(tmp_path: Path) -> None:
    path = tmp_path / "updates.sqlite3"
    authority = SQLiteModelRevisionAuthority(path)
    initial = _initial()
    authority.initialize(initial)
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1")
    receipt = _producer(_candidate(initial)).build_candidate(plan, proposal, initial)
    prepared = authority.prepare_successor(
        receipt,
        expected_generation=1,
        recovery_anchor_digest="8" * 64,
        validation_plan_digest="9" * 64,
    )
    reopened = SQLiteModelRevisionAuthority(path).load_prepared(proposal.digest())
    assert reopened == prepared
    assert reopened.build_receipt_digest == receipt.digest()


def test_tampered_durable_build_receipt_fails_closed_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "updates.sqlite3"
    authority = SQLiteModelRevisionAuthority(path)
    initial = _initial()
    authority.initialize(initial)
    plan = _plan(initial)
    proposal = plan.to_proposal("proposal-1")
    receipt = _producer(_candidate(initial)).build_candidate(plan, proposal, initial)
    authority.prepare_successor(
        receipt,
        expected_generation=1,
        recovery_anchor_digest="8" * 64,
        validation_plan_digest="9" * 64,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE prepared SET build_receipt=? WHERE proposal_digest=?",
            (b'{"junk":1}', proposal.digest()),
        )
        connection.commit()

    with pytest.raises(ModelRevisionIntegrityError):
        SQLiteModelRevisionAuthority(path).load_prepared(proposal.digest())


def test_durable_prepare_no_longer_accepts_raw_candidate_bypass(tmp_path: Path) -> None:
    authority = SQLiteModelRevisionAuthority(tmp_path / "updates.sqlite3")
    initial = _initial()
    authority.initialize(initial)
    with pytest.raises(TypeError):
        authority.prepare_successor(  # type: ignore[call-arg]
            _plan(initial).to_proposal("proposal-1"),
            initial,
            _candidate(initial),
            expected_generation=1,
            recovery_anchor_digest="8" * 64,
            validation_plan_digest="9" * 64,
        )
