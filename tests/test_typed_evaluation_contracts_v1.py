from __future__ import annotations

import math

import pytest

from noetrium_platform.research.experimentation.evaluation.api import (
    BranchReceipt,
    ComparabilityProof,
    PairedEvaluationResult,
    build_comparability_proof,
)


def _receipt(branch_id: str, *, metrics=(("utility", 1.0),), **changes) -> BranchReceipt:
    values = dict(
        branch_id=branch_id,
        source_checkpoint_id="checkpoint-1",
        workload_id="workload-1",
        environment_generation="environment-1",
        task_manifest_digest="tasks-1",
        branch_writes=(),
        lifetime_writes=(),
        private_to_method_flows=(),
        metrics=metrics,
    )
    values.update(changes)
    return BranchReceipt(**values)


def test_branch_receipt_rejects_metric_type_and_schema_drift() -> None:
    with pytest.raises(TypeError):
        _receipt("control", metrics=(("utility", "1.0"),))
    with pytest.raises(TypeError):
        _receipt("control", metrics=(("utility", True),))
    with pytest.raises(ValueError):
        _receipt("control", metrics=(("utility", math.nan),))
    with pytest.raises(ValueError, match="not finite"):
        _receipt("control", metrics=(("utility", 10**10000),))
    with pytest.raises(ValueError, match="duplicate metric"):
        _receipt("control", metrics=(("utility", 1.0), ("utility", 2.0)))


def test_branch_receipt_rejects_collection_and_identity_type_drift() -> None:
    with pytest.raises(TypeError):
        _receipt("control", branch_writes=[])
    with pytest.raises(TypeError):
        _receipt("control", workload_id=7)
    with pytest.raises(ValueError):
        _receipt(" ")


def test_comparability_proof_rejects_impossible_validity_state() -> None:
    with pytest.raises(ValueError, match="validity"):
        ComparabilityProof(True, "pair-1", ("mismatch",), "cp", "workload", "env", "tasks")
    with pytest.raises(ValueError, match="validity"):
        ComparabilityProof(False, "pair-1", (), "cp", "workload", "env", "tasks")


def test_comparability_requires_identical_metric_schema() -> None:
    proof = build_comparability_proof(
        _receipt("control", metrics=(("utility", 1.0), ("cost", 2.0))),
        _receipt("candidate", metrics=(("utility", 1.5),)),
    )
    assert proof.valid is False
    assert proof.violations == ("metric schema mismatch",)


def test_metric_order_does_not_break_comparability() -> None:
    proof = build_comparability_proof(
        _receipt("control", metrics=(("utility", 1.0), ("cost", 2.0))),
        _receipt("candidate", metrics=(("cost", 1.5), ("utility", 1.5))),
    )
    assert proof.valid is True
    assert proof.violations == ()


def test_paired_evaluation_result_binds_proof_to_control_identity() -> None:
    control = _receipt("control")
    candidate = _receipt("candidate")
    proof = build_comparability_proof(control, candidate)
    assert PairedEvaluationResult(control, candidate, proof).proof is proof
    wrong = ComparabilityProof(True, "pair-2", (), "other", "workload-1", "environment-1", "tasks-1")
    with pytest.raises(ValueError, match="source checkpoint"):
        PairedEvaluationResult(control, candidate, wrong)
