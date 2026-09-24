from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.lifecycle.api import (
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    StudyAssignment,
    StudyVariantSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskVerifierIsolation,
    TrialExecutionRequest,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadMethodReceipt,
    WorkloadTaskResult,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    StandardWorkloadMeasurementProjection,
    WorkloadTrialProvider,
)
from noetrium_platform.research.experimentation.workload.api import (
    StaticExperimentTaskProjection,
)


class _Workload:
    def __init__(self, result: WorkloadTaskResult) -> None:
        self.result = result
        self.calls = []

    def execute_one(self, task, context):
        self.calls.append((task, context))
        return self.result


def _protocol(*definitions: MeasurementDefinition) -> MeasurementProtocol:
    return MeasurementProtocol("workload-outcome", tuple(definitions))


def _success_definition() -> MeasurementDefinition:
    return MeasurementDefinition(
        "success",
        "bool.v1",
        MeasurementValueKind.BOOLEAN,
        semantic_kind="task_success",
    )


def _utility_definition() -> MeasurementDefinition:
    return MeasurementDefinition.scalar(
        "utility",
        schema_id="scalar.v1",
        semantic_kind="utility",
    )


def _steps_definition() -> MeasurementDefinition:
    return MeasurementDefinition.scalar(
        "steps",
        schema_id="scalar.v1",
        semantic_kind="steps",
    )


def _duration_definition() -> MeasurementDefinition:
    return MeasurementDefinition.scalar(
        "duration",
        schema_id="seconds.v1",
        unit="s",
        semantic_kind="duration_seconds",
    )


def _task_definition(*, verifier: bool = False) -> TaskDefinition:
    package = None
    if verifier:
        package = TaskPackageSpec(
            package_schema_id="benchmark.task-package.v1",
            instruction_digest="1" * 64,
            verifier_requirement_id="verifier.task",
            verifier_isolation=TaskVerifierIsolation.SHARED,
        )
    return TaskDefinition(
        "task-1",
        "1",
        "family",
        "task.v1",
        "2" * 64,
        package=package,
    )


def _request(
    protocol: MeasurementProtocol,
    *,
    protocol_identity: ExperimentTrialProtocolIdentity | None = None,
    verifier: bool = False,
) -> TrialExecutionRequest:
    task = _task_definition(verifier=verifier)
    assignment = StudyAssignment("study", "control", 0, "seed", task.task_id)
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
        protocol,
        protocol_identity or ExperimentTrialProtocolIdentity("trial.workload", "7" * 64),
        task,
    )


def _result() -> WorkloadTaskResult:
    return WorkloadTaskResult(
        task_id="task-1",
        family="family",
        success=True,
        utility=0.75,
        steps=4,
        duration_s=1.25,
        lineage_id="task-1",
        method_receipt=WorkloadMethodReceipt(
            run_id="method-run",
            program_digest="8" * 64,
            run_digest="9" * 64,
            status="succeeded",
            step_count=4,
            evidence_status="complete",
        ),
    )


def _provider(protocol: MeasurementProtocol, workload: _Workload) -> WorkloadTrialProvider:
    return WorkloadTrialProvider(
        protocol_identity=ExperimentTrialProtocolIdentity("trial.workload", "7" * 64),
        workload=workload,
        task_projection=StaticExperimentTaskProjection((
            ExperimentTaskSpec(
                "task-1",
                "family",
                "Solve the frozen task.",
                context="benchmark-visible context",
                max_steps=8,
                max_seconds=30,
            ),
        )),
        measurement_projection=StandardWorkloadMeasurementProjection(),
    )


def test_workload_trial_bridge_projects_task_executes_and_emits_typed_measurements() -> None:
    protocol = _protocol(
        _success_definition(),
        _utility_definition(),
        _steps_definition(),
        _duration_definition(),
    )
    workload = _Workload(_result())
    provider = _provider(protocol, workload)
    request = _request(protocol)

    receipt = provider.run_trial(request)

    assert receipt.request_digest == request.request_digest
    assert receipt.assignment_digest == request.assignment.assignment_digest
    assert len(workload.calls) == 1
    task, context = workload.calls[0]
    assert task.objective == "Solve the frozen task."
    assert context.run_id == request.run_id
    assert context.study_id == request.assignment.study_id
    assert context.condition_id == request.assignment.variant_id
    assert context.task_id == request.assignment.task_id
    assert context.operation_id == request.request_digest
    by_id = {row.measurement_id: row for row in receipt.measurements}
    assert by_id["success"].value.boolean is True
    assert by_id["utility"].value.scalar == 0.75
    assert by_id["steps"].value.scalar == 4.0
    assert by_id["duration"].value.scalar == 1.25
    for row in receipt.measurements:
        row.validate_against(protocol)


def test_standard_measurement_projection_refuses_unknown_benchmark_semantics() -> None:
    protocol = _protocol(
        MeasurementDefinition.scalar(
            "bleu",
            schema_id="scalar.v1",
            semantic_kind="bleu_score",
        )
    )
    provider = _provider(protocol, _Workload(_result()))
    with pytest.raises(ValueError, match="provide a project measurement projector"):
        provider.run_trial(_request(protocol))


def test_workload_trial_bridge_never_bypasses_declared_verifier_boundary() -> None:
    protocol = _protocol(_success_definition())
    provider = _provider(protocol, _Workload(_result()))
    with pytest.raises(RuntimeError, match="verifier-backed"):
        provider.run_trial(_request(protocol, verifier=True))


def test_workload_trial_bridge_fails_closed_on_protocol_identity_drift() -> None:
    protocol = _protocol(_success_definition())
    provider = _provider(protocol, _Workload(_result()))
    request = _request(
        protocol,
        protocol_identity=ExperimentTrialProtocolIdentity("trial.other", "a" * 64),
    )
    with pytest.raises(ValueError, match="protocol identity drift"):
        provider.run_trial(request)


def test_static_task_projection_fails_closed_on_unknown_task() -> None:
    protocol = _protocol(_success_definition())
    projection = StaticExperimentTaskProjection((
        ExperimentTaskSpec("other", "family", "Other task."),
    ))
    request = _request(protocol)
    with pytest.raises(KeyError, match="no unique task"):
        projection.task(request.assignment.task_id)
