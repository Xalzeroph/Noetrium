from __future__ import annotations

from types import SimpleNamespace

import pytest

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.study.api import (
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValue,
    MeasurementValueKind,
    StudyAssignment,
    StudyVariantSpec,
    TaskArtifactSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskVerifierArtifact,
    TaskVerifierIsolation,
    TaskVerifierReceipt,
    TaskVerifierRequest,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.study.runtime.trial import (
    TrialVerifierOrchestrator,
    _require_measurements,
)


def _protocol() -> MeasurementProtocol:
    return MeasurementProtocol(
        "verifier-output",
        (
            MeasurementDefinition(
                "score",
                "scalar-v1",
                MeasurementValueKind.SCALAR,
            ),
        ),
    )


def _package(
    isolation: TaskVerifierIsolation = TaskVerifierIsolation.SEPARATE,
) -> TaskPackageSpec:
    return TaskPackageSpec(
        package_schema_id="benchmark.task-package.v1",
        instruction_digest="1" * 64,
        verifier_requirement_id="verifier.task",
        verifier_isolation=isolation,
        verifier_environment_requirement_id=(
            "environment.verifier"
            if isolation is TaskVerifierIsolation.SEPARATE
            else None
        ),
        artifacts=(
            TaskArtifactSpec("answer", "artifacts/answer.json"),
            TaskArtifactSpec(
                "trace",
                "artifacts/trace.jsonl",
                required=False,
            ),
        ),
    )


def _task(
    isolation: TaskVerifierIsolation = TaskVerifierIsolation.SEPARATE,
) -> TaskDefinition:
    return TaskDefinition(
        "task-1",
        "1",
        "generic",
        "task.v1",
        "2" * 64,
        package=_package(isolation),
    )


def _artifact(
    declaration: TaskArtifactSpec,
    suffix: str,
) -> TaskVerifierArtifact:
    return TaskVerifierArtifact(
        declaration,
        ArtifactReference(
            f"ref-{suffix}",
            PLATFORM_SCOPE,
            f"artifact-{suffix}",
            1,
        ),
    )


def _trial_request(task: TaskDefinition) -> TrialExecutionRequest:
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
    binding = VariantBinding(
        variant,
        "4" * 64,
        "provider",
        "none",
        "control",
    )
    return TrialExecutionRequest(
        "project",
        "run",
        "5" * 64,
        OptionalIdentityFacet(),
        OptionalIdentityFacet(),
        OptionalIdentityFacet("6" * 64),
        assignment,
        binding,
        _protocol(),
        ExperimentTrialProtocolIdentity("trial.test", "7" * 64),
        task,
    )


def _handoff(task: TaskDefinition, *artifacts: TaskVerifierArtifact) -> TaskVerifierRequest:
    return TaskVerifierRequest.for_trial(
        trial_request=_trial_request(task),
        artifacts=tuple(artifacts),
    )


def test_verifier_handoff_only_accepts_declared_artifacts() -> None:
    task = _task()
    assert task.package is not None
    answer = _artifact(task.package.artifacts[0], "answer")
    request = _handoff(task, answer)
    assert tuple(
        row.declaration.artifact_id for row in request.artifacts
    ) == ("answer",)

    undeclared = _artifact(
        TaskArtifactSpec("secret", "private/secret.txt"),
        "secret",
    )
    with pytest.raises(ValueError, match="undeclared artifacts"):
        _handoff(task, answer, undeclared)


def test_verifier_handoff_requires_all_required_artifacts() -> None:
    task = _task()
    with pytest.raises(ValueError, match="missing required artifacts"):
        _handoff(task)


def test_verifier_request_is_minimal_but_sufficient_for_measurement_identity() -> None:
    task = _task()
    assert task.package is not None
    request = _handoff(task, _artifact(task.package.artifacts[0], "answer"))

    assert not hasattr(request, "environment")
    assert not hasattr(request, "participant_session")
    assert not hasattr(request, "workdir")

    measurement = request.measurement(
        "score",
        MeasurementValue(MeasurementValueKind.SCALAR, scalar=1.0),
        producer_id="verifier.task",
        producer_revision_digest="a" * 64,
        logical_time="verifier:1",
        lineage_refs=(request.artifacts[0].reference,),
    )
    measurement.validate_against(request.measurement_protocol)
    assert measurement.project_id == request.project_id
    assert measurement.run_id == request.run_id
    assert measurement.assignment_digest == request.assignment_digest
    assert measurement.lineage_refs == (request.artifacts[0].reference,)


def test_separate_verifier_requires_isolation_evidence() -> None:
    task = _task(TaskVerifierIsolation.SEPARATE)
    assert task.package is not None
    request = _handoff(task, _artifact(task.package.artifacts[0], "answer"))
    with pytest.raises(ValueError, match="isolation evidence"):
        TaskVerifierReceipt(request, ())

    evidence = ArtifactReference(
        "ref-isolation",
        PLATFORM_SCOPE,
        "artifact-isolation-proof",
        1,
    )
    receipt = TaskVerifierReceipt(
        request,
        (),
        (evidence,),
    )
    assert receipt.request == request


def test_shared_verifier_does_not_invent_isolation_evidence_requirement() -> None:
    task = _task(TaskVerifierIsolation.SHARED)
    assert task.package is not None
    request = _handoff(task, _artifact(task.package.artifacts[0], "answer"))
    receipt = TaskVerifierReceipt(request, ())
    assert receipt.evidence_refs == ()


def test_trial_runtime_fails_closed_when_declared_verifier_receipt_is_missing() -> None:
    request = _trial_request(_task())
    receipt = TrialExecutionReceipt(
        request.request_digest,
        request.assignment.assignment_digest,
        (),
    )
    plan = SimpleNamespace(measurement_protocol=request.measurement_protocol)
    with pytest.raises(ValueError, match="declares verifier"):
        _require_measurements(plan, request, receipt)


def test_trial_request_binds_exact_task_package_identity() -> None:
    task = _task()
    request = _trial_request(task)
    assert request.task == task
    assert task.package is not None

    changed_task = TaskDefinition(
        "task-1",
        "2",
        "generic",
        "task.v1",
        "9" * 64,
        package=task.package,
    )
    changed = _trial_request(changed_task)
    assert changed.request_digest != request.request_digest


def test_core_orchestrates_verifier_after_artifact_only_execution_stage() -> None:
    task = _task()
    request = _trial_request(task)
    assert task.package is not None
    answer = _artifact(task.package.artifacts[0], "answer")
    execution_evidence = ArtifactReference(
        "ref-execution",
        PLATFORM_SCOPE,
        "artifact-execution-proof",
        1,
    )
    stage = TrialExecutionStageReceipt(
        request.request_digest,
        request.assignment.assignment_digest,
        verifier_artifacts=(answer,),
        evidence_refs=(execution_evidence,),
    )

    class Verifier:
        def __init__(self) -> None:
            self.seen: TaskVerifierRequest | None = None

        def verify(self, verifier_request: TaskVerifierRequest) -> TaskVerifierReceipt:
            self.seen = verifier_request
            measurement = verifier_request.measurement(
                "score",
                MeasurementValue(MeasurementValueKind.SCALAR, scalar=0.75),
                producer_id="verifier.task",
                producer_revision_digest="b" * 64,
                logical_time="verifier:1",
                lineage_refs=(verifier_request.artifacts[0].reference,),
            )
            isolation = ArtifactReference(
                "ref-isolation",
                PLATFORM_SCOPE,
                "artifact-isolation-proof",
                1,
            )
            return TaskVerifierReceipt(
                verifier_request,
                (measurement,),
                (isolation,),
            )

    verifier = Verifier()
    final = TrialVerifierOrchestrator().finalize(
        request,
        stage,
        verifier=verifier,
    )
    assert verifier.seen is not None
    assert final.verifier_receipt is not None
    assert final.measurements == final.verifier_receipt.measurements
    assert final.evidence_refs == (
        execution_evidence,
        final.verifier_receipt.evidence_refs[0],
    )


def test_declared_verifier_cannot_be_bypassed_with_provider_final_receipt() -> None:
    request = _trial_request(_task())
    provider_final = TrialExecutionReceipt(
        request.request_digest,
        request.assignment.assignment_digest,
        (),
    )
    with pytest.raises(ValueError, match="execution-stage receipt"):
        TrialVerifierOrchestrator().finalize(request, provider_final)
