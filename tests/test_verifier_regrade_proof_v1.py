from __future__ import annotations

import pytest

from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementSetOutcome,
    MeasurementValueKind,
    StudyAssignment,
    StudyVariantSpec,
    TaskArtifactSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskVerifierArtifact,
    TaskVerifierArtifactCut,
    TaskVerifierIsolation,
    TaskVerifierRegradeDefinition,
    TaskVerifierRegradeNotReady,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.composition import (
    build_task_verifier_regrade_proof,
)


class _ContentAuthority:
    def __init__(self, by_reference: dict[str, ArtifactContentIdentity]) -> None:
        self.by_reference = by_reference

    def verify(self, identity: ArtifactContentIdentity) -> ArtifactContentIdentity:
        return identity

    def load(self, artifact_id: str) -> ArtifactContentIdentity:
        matches = tuple(
            identity
            for identity in self.by_reference.values()
            if identity.artifact_id == artifact_id
        )
        if len(matches) != 1:
            raise KeyError(artifact_id)
        return matches[0]

    def snapshot_reference(self, reference_id, scope):
        del scope
        return self.by_reference[reference_id]


def _protocol() -> MeasurementProtocol:
    return MeasurementProtocol(
        "regrade-output",
        (
            MeasurementDefinition(
                "score",
                "scalar-v1",
                MeasurementValueKind.SCALAR,
            ),
        ),
    )


def _task() -> TaskDefinition:
    return TaskDefinition(
        "task-1",
        "1",
        "generic",
        "task.v1",
        "1" * 64,
        package=TaskPackageSpec(
            package_schema_id="benchmark.task-package.v1",
            instruction_digest="2" * 64,
            verifier_requirement_id="verifier.original",
            verifier_isolation=TaskVerifierIsolation.SEPARATE,
            verifier_environment_requirement_id="environment.verifier",
            artifacts=(
                TaskArtifactSpec("answer", "artifacts/answer.json"),
                TaskArtifactSpec(
                    "trace",
                    "artifacts/trace.jsonl",
                    required=False,
                ),
            ),
        ),
    )


def _request(task: TaskDefinition) -> TrialExecutionRequest:
    assignment = StudyAssignment(
        "study",
        "control",
        0,
        "seed",
        task.task_id,
    )
    variant = StudyVariantSpec(
        "control",
        VariantKind.CONTROL,
        "provider",
        "3" * 64,
    )
    return TrialExecutionRequest(
        "project",
        "run",
        "4" * 64,
        OptionalIdentityFacet(),
        OptionalIdentityFacet(),
        OptionalIdentityFacet("5" * 64),
        assignment,
        VariantBinding(
            variant,
            "6" * 64,
            "provider",
            "none",
            "control",
        ),
        _protocol(),
        ExperimentTrialProtocolIdentity("trial.test", "7" * 64),
        task,
    )


def _source() -> tuple[
    TrialExecutionReceipt,
    TaskVerifierArtifactCut,
    TaskArtifactSpec,
    ArtifactReference,
]:
    task = _task()
    request = _request(task)
    assert task.package is not None
    answer_spec = task.package.artifacts[0]
    answer_ref = ArtifactReference(
        "ref-answer",
        PLATFORM_SCOPE,
        "artifact-answer",
        1,
    )
    cut = TaskVerifierArtifactCut.for_trial(
        trial_request=request,
        artifacts=(TaskVerifierArtifact(answer_spec, answer_ref),),
    )
    receipt = TrialExecutionReceipt(
        request.request_digest,
        request.assignment.assignment_digest,
        (),
        MeasurementSetOutcome.unscored(
            request.measurement_protocol,
            reason_code="original_grader_failed",
        ),
        verifier_artifact_cut=cut,
    )
    return receipt, cut, answer_spec, answer_ref


def _definition(
    receipt: TrialExecutionReceipt,
    cut: TaskVerifierArtifactCut,
    required: tuple[TaskArtifactSpec, ...],
) -> TaskVerifierRegradeDefinition:
    return TaskVerifierRegradeDefinition(
        "regrade-1",
        receipt.receipt_digest,
        cut.cut_digest,
        "verifier.new",
        "8" * 64,
        _protocol().semantic_digest,
        required,
    )


def test_regrade_depends_on_recorded_artifact_cut_not_old_verifier_result() -> None:
    receipt, cut, answer_spec, answer_ref = _source()
    assert receipt.verifier_receipt is None
    assert receipt.measurement_outcome.reason_code == "original_grader_failed"

    proof = build_task_verifier_regrade_proof(
        _definition(receipt, cut, (answer_spec,)),
        receipt,
        _ContentAuthority(
            {
                answer_ref.reference_id: ArtifactContentIdentity(
                    answer_ref.artifact_id,
                    "9" * 64,
                )
            }
        ),
    )

    assert proof.source_trial_receipt_digest == receipt.receipt_digest
    assert proof.source_artifact_cut_digest == cut.cut_digest
    assert proof.artifact_bindings[0].content_identity.content_sha256 == "9" * 64


def test_regrade_rejects_changed_artifact_declaration() -> None:
    receipt, cut, answer_spec, answer_ref = _source()
    changed = TaskArtifactSpec(
        answer_spec.artifact_id,
        "different/answer.json",
    )
    with pytest.raises(TaskVerifierRegradeNotReady) as exc:
        build_task_verifier_regrade_proof(
            _definition(receipt, cut, (changed,)),
            receipt,
            _ContentAuthority(
                {
                    answer_ref.reference_id: ArtifactContentIdentity(
                        answer_ref.artifact_id,
                        "9" * 64,
                    )
                }
            ),
        )
    assert exc.value.code == "ARTIFACT_DECLARATION_DRIFT"


def test_regrade_rejects_missing_required_artifact() -> None:
    receipt, cut, _, answer_ref = _source()
    trace = TaskArtifactSpec("trace", "artifacts/trace.jsonl")
    with pytest.raises(TaskVerifierRegradeNotReady) as exc:
        build_task_verifier_regrade_proof(
            _definition(receipt, cut, (trace,)),
            receipt,
            _ContentAuthority(
                {
                    answer_ref.reference_id: ArtifactContentIdentity(
                        answer_ref.artifact_id,
                        "9" * 64,
                    )
                }
            ),
        )
    assert exc.value.code == "ARTIFACT_MISSING"


def test_regrade_rejects_reference_resolving_to_foreign_artifact() -> None:
    receipt, cut, answer_spec, answer_ref = _source()
    with pytest.raises(TaskVerifierRegradeNotReady) as exc:
        build_task_verifier_regrade_proof(
            _definition(receipt, cut, (answer_spec,)),
            receipt,
            _ContentAuthority(
                {
                    answer_ref.reference_id: ArtifactContentIdentity(
                        "artifact-foreign",
                        "9" * 64,
                    )
                }
            ),
        )
    assert exc.value.code == "ARTIFACT_REFERENCE_DRIFT"


def test_regrade_definition_is_bound_to_source_receipt_and_cut() -> None:
    receipt, cut, answer_spec, answer_ref = _source()
    definition = TaskVerifierRegradeDefinition(
        "regrade-1",
        "a" * 64,
        cut.cut_digest,
        "verifier.new",
        "8" * 64,
        _protocol().semantic_digest,
        (answer_spec,),
    )
    with pytest.raises(TaskVerifierRegradeNotReady) as exc:
        build_task_verifier_regrade_proof(
            definition,
            receipt,
            _ContentAuthority(
                {
                    answer_ref.reference_id: ArtifactContentIdentity(
                        answer_ref.artifact_id,
                        "9" * 64,
                    )
                }
            ),
        )
    assert exc.value.code == "SOURCE_RECEIPT_DRIFT"
