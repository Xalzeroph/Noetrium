"""Study-owned Trial provider, verifier, and measurement projection semantics."""

from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    TaskVerifierPort,
    TaskVerifierReceipt,
    TaskVerifierRequest,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    TrialMeasurementProjectionPort,
    TrialTaskProjectionPort,
)
from noetrium_platform.research.experimentation.api.research_compiler import (
    CompiledResearchPlan,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadTaskExecutionPort,
    WorkloadTaskResult,
)


class StandardWorkloadMeasurementProjection:
    """Generic Trial measurement projection for standard Workload outcomes."""

    _SUPPORTED = frozenset({
        "task_success",
        "utility",
        "steps",
        "duration_seconds",
        "blocked",
    })

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "projection": "standard-workload-measurements.v1",
            "semantic_kinds": tuple(sorted(self._SUPPORTED)),
        })

    @staticmethod
    def _value(definition, result: WorkloadTaskResult) -> MeasurementValue:
        semantic = definition.semantic_kind
        if semantic == "task_success":
            if definition.value_kind is MeasurementValueKind.BOOLEAN:
                return MeasurementValue(
                    MeasurementValueKind.BOOLEAN,
                    boolean=result.success,
                )
            if definition.value_kind is MeasurementValueKind.SCALAR:
                return MeasurementValue(
                    MeasurementValueKind.SCALAR,
                    scalar=1.0 if result.success else 0.0,
                )
        elif semantic == "utility" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(MeasurementValueKind.SCALAR, scalar=float(result.utility))
        elif semantic == "steps" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(MeasurementValueKind.SCALAR, scalar=float(result.steps))
        elif semantic == "duration_seconds" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=float(result.duration_s),
            )
        elif semantic == "blocked" and definition.value_kind is MeasurementValueKind.BOOLEAN:
            return MeasurementValue(MeasurementValueKind.BOOLEAN, boolean=result.blocked)
        raise ValueError(
            "standard workload measurement projection cannot represent "
            f"semantic_kind={semantic!r} as value_kind={definition.value_kind.value!r}"
        )

    def project(
        self,
        request: TrialExecutionRequest,
        result: object,
    ) -> tuple[MeasurementRecord, ...]:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError("measurement projection requires TrialExecutionRequest")
        if not isinstance(result, WorkloadTaskResult):
            raise TypeError("measurement projection requires WorkloadTaskResult")
        protocol = request.measurement_protocol
        producer_revision = self.identity_digest
        rows: list[MeasurementRecord] = []
        for definition in protocol.definitions:
            if definition.semantic_kind not in self._SUPPORTED:
                raise ValueError(
                    "standard workload measurement projection has no semantic mapping for "
                    f"{definition.semantic_kind!r}; provide a project measurement projector"
                )
            rows.append(MeasurementRecord(
                project_id=request.project_id,
                study_id=request.assignment.study_id,
                run_id=request.run_id,
                assignment_digest=request.assignment.assignment_digest,
                variant_id=request.assignment.variant_id,
                producer_id="noetrium.workload-trial-provider",
                producer_revision_digest=producer_revision,
                measurement_id=definition.measurement_id,
                schema_id=definition.schema_id,
                measurement_semantic_digest=definition.semantic_contract_digest,
                measurement_protocol_semantic_digest=protocol.semantic_digest,
                value=self._value(definition, result),
                logical_time=(
                    f"assignment:{request.assignment.repetition}:"
                    f"{request.assignment.seed}:{definition.measurement_id}"
                ),
                intervention=request.intervention,
                revision=request.revision,
            ))
        return tuple(rows)


class WorkloadTrialProvider:
    """Study-owned bridge from a frozen Trial request to generic Workload execution."""

    def __init__(
        self,
        *,
        protocol_identity: object,
        workload: WorkloadTaskExecutionPort,
        task_projection: TrialTaskProjectionPort,
        measurement_projection: TrialMeasurementProjectionPort,
    ) -> None:
        digest = getattr(protocol_identity, "digest", None)
        if not callable(digest):
            raise TypeError("workload trial provider requires protocol identity")
        canonical_digest_value = digest()
        if type(canonical_digest_value) is not str or len(canonical_digest_value) != 64:
            raise TypeError("workload trial protocol identity digest is invalid")
        if not isinstance(task_projection, TrialTaskProjectionPort):
            raise TypeError("workload trial provider requires TrialTaskProjectionPort")
        if not isinstance(measurement_projection, TrialMeasurementProjectionPort):
            raise TypeError("workload trial provider requires TrialMeasurementProjectionPort")
        if not callable(getattr(workload, "execute_one", None)):
            raise TypeError("workload trial provider requires WorkloadTaskExecutionPort")
        for field_name, value in (
            ("task projection", task_projection.identity_digest),
            ("measurement projection", measurement_projection.identity_digest),
        ):
            if type(value) is not str or len(value) != 64:
                raise TypeError(f"{field_name} identity digest is invalid")
        self.protocol_identity = protocol_identity
        self._workload = workload
        self._task_projection = task_projection
        self._measurement_projection = measurement_projection
        self.identity_digest = canonical_digest({
            "provider": "workload-trial-provider.v1",
            "protocol_identity": canonical_digest_value,
            "task_projection": task_projection.identity_digest,
            "measurement_projection": measurement_projection.identity_digest,
        })

    def run_trial(self, request: TrialExecutionRequest) -> TrialExecutionReceipt:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError("workload trial provider requires TrialExecutionRequest")
        if request.protocol_identity != self.protocol_identity:
            raise ValueError("trial request protocol identity drift")
        if (
            request.task is not None
            and request.task.package is not None
            and request.task.package.verifier_requirement_id is not None
        ):
            raise RuntimeError(
                "verifier-backed benchmark tasks require an explicit verifier-stage "
                "trial provider; workload trial provider will not bypass verifier isolation"
            )
        task_id = request.assignment.task_id
        if task_id is None:
            raise ValueError("workload trial provider requires task-level assignment")
        task = self._task_projection.task(task_id)
        if getattr(task, "task_id", None) != task_id:
            raise ValueError("projected workload task identity drift")
        context = ExecutionContext(
            run_id=request.run_id,
            trace_id=request.request_digest,
            span_id=f"trial:{request.assignment.assignment_digest[:16]}",
            study_id=request.assignment.study_id,
            condition_id=request.assignment.variant_id,
            task_id=task_id,
            operation_id=request.request_digest,
            component_id="workload-trial-provider",
        )
        result = self._workload.execute_one(task, context)
        if not isinstance(result, WorkloadTaskResult):
            raise TypeError("workload trial provider requires WorkloadTaskResult")
        if result.task_id != task_id:
            raise ValueError("workload result task identity drift")
        measurements = self._measurement_projection.project(request, result)
        for row in measurements:
            row.validate_against(request.measurement_protocol)
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
        )


def _require_measurements(
    plan: CompiledResearchPlan,
    request: TrialExecutionRequest,
    receipt: TrialExecutionReceipt,
) -> tuple[MeasurementRecord, ...]:
    if receipt.request_digest != request.request_digest:
        raise ValueError("trial receipt does not bind the execution request")
    if receipt.assignment_digest != request.assignment.assignment_digest:
        raise ValueError("trial receipt does not bind the assignment")

    task = request.task
    package = None if task is None else task.package
    verifier_required = package is not None and package.verifier_requirement_id is not None
    if verifier_required:
        verifier = receipt.verifier_receipt
        if verifier is None:
            raise ValueError("task package declares verifier but trial receipt has none")
        if verifier.request.source_trial_request_digest != request.request_digest:
            raise ValueError("verifier receipt does not bind the trial request")
        if verifier.request.task_digest != task.task_digest:
            raise ValueError("verifier receipt does not bind the frozen task")
        if verifier.request.task_package_digest != package.package_digest:
            raise ValueError("verifier receipt does not bind the frozen task package")
        if (
            verifier.request.measurement_protocol_digest
            != request.measurement_protocol.protocol_digest
        ):
            raise ValueError("verifier receipt measurement protocol drifted")
        if verifier.measurements != receipt.measurements:
            raise ValueError(
                "trial measurements must be exactly the verifier measurements"
            )
    elif receipt.verifier_receipt is not None:
        raise ValueError(
            "trial receipt cannot attach verifier evidence when task declares none"
        )

    expected_ids = {row.measurement_id for row in plan.measurement_protocol.definitions}
    actual_ids = tuple(row.measurement_id for row in receipt.measurements)
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ValueError("trial receipt does not exactly cover the measurement protocol")

    for record in receipt.measurements:
        record.validate_against(plan.measurement_protocol)
        if record.project_id != request.project_id or record.study_id != request.assignment.study_id:
            raise ValueError("trial measurement belongs to another project or study")
        if record.run_id != request.run_id:
            raise ValueError("trial measurement belongs to another run")
        if record.assignment_digest != request.assignment.assignment_digest:
            raise ValueError("trial measurement does not bind the assignment")
        if record.variant_id != request.assignment.variant_id:
            raise ValueError("trial measurement variant does not match assignment")
        if record.intervention != request.intervention:
            raise ValueError("trial measurement intervention does not match request")
        if record.revision != request.revision:
            raise ValueError("trial measurement revision does not match request")
    return receipt.measurements


class TrialVerifierOrchestrator:
    """Finalize one provider stage through the task-declared verifier boundary."""

    def finalize(
        self,
        request: TrialExecutionRequest,
        provider_receipt: TrialExecutionReceipt | TrialExecutionStageReceipt,
        *,
        verifier: TaskVerifierPort | None = None,
    ) -> TrialExecutionReceipt:
        if type(request) is not TrialExecutionRequest:
            raise TypeError("trial verifier orchestration requires TrialExecutionRequest")
        if type(provider_receipt) not in {
            TrialExecutionReceipt,
            TrialExecutionStageReceipt,
        }:
            raise TypeError(
                "trial provider must return TrialExecutionReceipt or "
                "TrialExecutionStageReceipt"
            )
        if provider_receipt.request_digest != request.request_digest:
            raise ValueError("trial provider receipt does not bind the execution request")
        if provider_receipt.assignment_digest != request.assignment.assignment_digest:
            raise ValueError("trial provider receipt does not bind the assignment")

        task = request.task
        package = None if task is None else task.package
        verifier_required = (
            package is not None and package.verifier_requirement_id is not None
        )
        if not verifier_required:
            if type(provider_receipt) is TrialExecutionReceipt:
                return provider_receipt
            if provider_receipt.verifier_artifacts:
                raise ValueError(
                    "trial without declared verifier cannot export verifier artifacts"
                )
            return TrialExecutionReceipt(
                request_digest=provider_receipt.request_digest,
                assignment_digest=provider_receipt.assignment_digest,
                measurements=provider_receipt.measurements,
                evidence_refs=provider_receipt.evidence_refs,
            )

        if type(provider_receipt) is not TrialExecutionStageReceipt:
            raise ValueError(
                "task-declared verifier requires an execution-stage receipt"
            )
        if provider_receipt.measurements:
            raise ValueError(
                "task-declared verifier forbids provider-produced final measurements"
            )
        if verifier is None:
            raise ValueError("task-declared verifier requires TaskVerifierPort")

        verifier_request = TaskVerifierRequest.for_trial(
            trial_request=request,
            artifacts=provider_receipt.verifier_artifacts,
        )
        verifier_receipt = verifier.verify(verifier_request)
        if type(verifier_receipt) is not TaskVerifierReceipt:
            raise TypeError("task verifier must return TaskVerifierReceipt")
        if verifier_receipt.request != verifier_request:
            raise ValueError("task verifier receipt does not bind the exact handoff")

        evidence_refs = tuple(
            dict.fromkeys(
                provider_receipt.evidence_refs + verifier_receipt.evidence_refs
            )
        )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=verifier_receipt.measurements,
            evidence_refs=evidence_refs,
            verifier_receipt=verifier_receipt,
        )


__all__ = [
    "StandardWorkloadMeasurementProjection",
    "TrialVerifierOrchestrator",
    "WorkloadTrialProvider",
]
