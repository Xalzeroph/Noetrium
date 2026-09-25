from __future__ import annotations

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.research.experimentation.workbench.api import (
    CandidateProgramExecutionReceipt,
    CandidateProgramExecutionRequest,
    CandidateProgramExecutionStatus,
    CandidateProgramIdentity,
)


def _candidate(
    candidate_id: str,
    generation: int,
    content: str,
    parents: tuple[str, ...] = (),
) -> CandidateProgramIdentity:
    return CandidateProgramIdentity(
        candidate_id=candidate_id,
        generation=generation,
        source=ArtifactContentIdentity(
            f"artifact:{candidate_id}",
            content,
        ),
        language="python",
        entrypoint="forward",
        interface_schema_id="candidate.forward.v1",
        parent_candidate_digests=parents,
    )


def test_candidate_program_identity_binds_source_generation_and_lineage() -> None:
    root = _candidate("root", 0, "a" * 64)
    child = _candidate("child", 1, "b" * 64, (root.candidate_digest,))

    assert child.parent_candidate_digests == (root.candidate_digest,)
    assert child.candidate_digest != root.candidate_digest

    changed_source = _candidate(
        "child",
        1,
        "c" * 64,
        (root.candidate_digest,),
    )
    assert changed_source.candidate_digest != child.candidate_digest


def test_candidate_execution_request_binds_exact_benchmark_evaluator_and_isolation() -> None:
    candidate = _candidate("candidate", 3, "d" * 64)
    request = CandidateProgramExecutionRequest(
        candidate=candidate,
        benchmark_cut_digest="1" * 64,
        evaluator_digest="2" * 64,
        isolation_requirement_id="software.untrusted-python",
        input_artifacts=(
            ArtifactContentIdentity("artifact:task-cut", "3" * 64),
        ),
        resource_requirement_digest="4" * 64,
    )

    changed_cut = CandidateProgramExecutionRequest(
        candidate=candidate,
        benchmark_cut_digest="5" * 64,
        evaluator_digest="2" * 64,
        isolation_requirement_id="software.untrusted-python",
        input_artifacts=(
            ArtifactContentIdentity("artifact:task-cut", "3" * 64),
        ),
        resource_requirement_digest="4" * 64,
    )

    assert request.request_digest != changed_cut.request_digest


def test_candidate_execution_receipt_references_measurement_authority_without_copying_it() -> None:
    request = CandidateProgramExecutionRequest(
        candidate=_candidate("candidate", 1, "d" * 64),
        benchmark_cut_digest="1" * 64,
        evaluator_digest="2" * 64,
        isolation_requirement_id="software.untrusted-python",
    )
    receipt = CandidateProgramExecutionReceipt(
        request_digest=request.request_digest,
        status=CandidateProgramExecutionStatus.SUCCEEDED,
        output_artifacts=(
            ArtifactContentIdentity("artifact:stdout", "6" * 64),
        ),
        measurement_record_digests=("7" * 64,),
        evidence_digests=("8" * 64,),
        isolation_evidence_digests=("9" * 64,),
    )

    assert receipt.request_digest == request.request_digest
    assert receipt.measurement_record_digests == ("7" * 64,)
    assert len(receipt.receipt_digest) == 64


def test_failed_candidate_execution_requires_explicit_failure_code() -> None:
    with pytest.raises(ValueError, match="requires failure_code"):
        CandidateProgramExecutionReceipt(
            request_digest="1" * 64,
            status=CandidateProgramExecutionStatus.FAILED,
        )
