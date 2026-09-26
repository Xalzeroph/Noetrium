"""Study-owned Trial provider, verifier, and measurement projection semantics."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    TaskArtifactSpec,
    TaskVerifierArtifact,
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
    WorkloadGraphExecutionPort,
    WorkloadGraphResult,
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
        "resource_usage",
    })

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "projection": "standard-workload-measurements.v2",
            "semantic_kinds": tuple(sorted(self._SUPPORTED)),
        })

    @staticmethod
    def _value(
        definition,
        result: WorkloadTaskResult | WorkloadGraphResult,
    ) -> MeasurementValue:
        rows = (
            result.task_results
            if isinstance(result, WorkloadGraphResult)
            else (result,)
        )
        semantic = definition.semantic_kind
        if semantic == "task_success":
            if definition.value_kind is MeasurementValueKind.BOOLEAN:
                return MeasurementValue(
                    MeasurementValueKind.BOOLEAN,
                    boolean=all(row.success for row in rows),
                )
            if definition.value_kind is MeasurementValueKind.SCALAR:
                return MeasurementValue(
                    MeasurementValueKind.SCALAR,
                    scalar=(
                        sum(1.0 for row in rows if row.success) / len(rows)
                    ),
                )
        elif semantic == "utility" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=sum(float(row.utility) for row in rows) / len(rows),
            )
        elif semantic == "steps" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=float(sum(row.steps for row in rows)),
            )
        elif semantic == "duration_seconds" and definition.value_kind is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=float(sum(row.duration_s for row in rows)),
            )
        elif semantic == "blocked" and definition.value_kind is MeasurementValueKind.BOOLEAN:
            return MeasurementValue(
                MeasurementValueKind.BOOLEAN,
                boolean=any(row.blocked for row in rows),
            )
        elif semantic == "resource_usage" and definition.value_kind is MeasurementValueKind.SCALAR:
            values = tuple(row.diagnostics.get(definition.measurement_id) for row in rows)
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in values
            ):
                raise KeyError(
                    "workload result has no numeric resource-usage diagnostic "
                    f"{definition.measurement_id!r}"
                )
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=sum(float(value) for value in values),
            )
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
        if not isinstance(result, (WorkloadTaskResult, WorkloadGraphResult)):
            raise TypeError(
                "measurement projection requires WorkloadTaskResult "
                "or WorkloadGraphResult"
            )
        protocol = request.measurement_protocol
        producer_revision = self.identity_digest
        verifier_required = any(
            definition.package is not None
            and definition.package.verifier_requirement_id is not None
            for definition in request.task_definitions
        )
        verifier_owned = frozenset({"task_success", "utility"})
        rows: list[MeasurementRecord] = []
        for definition in protocol.definitions:
            if definition.semantic_kind not in self._SUPPORTED:
                continue
            if verifier_required and definition.semantic_kind in verifier_owned:
                continue
            try:
                value = self._value(definition, result)
            except KeyError:
                continue
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
                value=value,
                logical_time=(
                    f"assignment:{request.assignment.repetition}:"
                    f"{request.assignment.seed}:{definition.measurement_id}"
                ),
                intervention=request.intervention,
                revision=request.revision,
            ))
        return tuple(rows)


class WorkloadTrialProvider:
    """Execute every assignment through the universal workload graph runtime."""

    def __init__(
        self,
        *,
        protocol_identity: object,
        workload: WorkloadGraphExecutionPort,
        task_projection: TrialTaskProjectionPort,
        measurement_projection: TrialMeasurementProjectionPort,
    ) -> None:
        digest = getattr(protocol_identity, "digest", None)
        if not callable(digest):
            raise TypeError("workload trial provider requires protocol identity")
        protocol_digest = digest()
        if type(protocol_digest) is not str or len(protocol_digest) != 64:
            raise TypeError("workload trial protocol identity digest is invalid")
        if not callable(getattr(workload, "execute_graph", None)):
            raise TypeError(
                "workload trial provider requires WorkloadGraphExecutionPort"
            )
        if not isinstance(task_projection, TrialTaskProjectionPort):
            raise TypeError(
                "workload trial provider requires TrialTaskProjectionPort"
            )
        if not isinstance(
            measurement_projection,
            TrialMeasurementProjectionPort,
        ):
            raise TypeError(
                "workload trial provider requires TrialMeasurementProjectionPort"
            )
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
        self.identity_digest = canonical_digest(
            {
                "provider": "workload-trial-provider.v2",
                "protocol_identity": protocol_digest,
                "task_projection": task_projection.identity_digest,
                "measurement_projection": measurement_projection.identity_digest,
            }
        )

    def run_trial(
        self,
        request: TrialExecutionRequest,
    ) -> TrialExecutionReceipt:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError(
                "workload trial provider requires TrialExecutionRequest"
            )
        if request.protocol_identity != self.protocol_identity:
            raise ValueError("trial request protocol identity drift")
        if any(
            definition.package is not None
            and definition.package.verifier_requirement_id is not None
            for definition in request.task_definitions
        ):
            raise RuntimeError(
                "verifier-backed benchmark tasks require verifier isolation; "
                "the universal workload provider will not bypass that boundary"
            )

        tasks = tuple(
            self._task_projection.task(request, definition)
            for definition in request.task_definitions
        )
        expected_ids = request.assignment.workload.task_ids
        actual_ids = tuple(
            getattr(task, "task_id", None)
            for task in tasks
        )
        if actual_ids != expected_ids:
            raise ValueError(
                "projected workload graph task identity/order drift"
            )

        context = ExecutionContext(
            run_id=request.run_id,
            trace_id=request.request_digest,
            span_id=f"trial:{request.assignment.assignment_digest[:16]}",
            study_id=request.assignment.study_id,
            condition_id=request.assignment.variant_id,
            condition_selections=tuple(
                (row.factor_id, row.level_id)
                for row in request.intervention_spec.selections
            ),
            lifetime_id=request.assignment.assignment_digest,
            task_id=None,
            operation_id=request.request_digest,
            component_id="workload-trial-provider",
        )
        result = self._workload.execute_graph(
            tasks,
            request.assignment.workload,
            context,
        )
        if not isinstance(result, WorkloadGraphResult):
            raise TypeError(
                "workload trial provider requires WorkloadGraphResult"
            )
        if result.task_ids != expected_ids:
            raise ValueError(
                "workload graph result task identity/order drift"
            )

        measurements = self._measurement_projection.project(
            request,
            result,
        )
        for row in measurements:
            row.validate_against(request.measurement_protocol)
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
        )


@runtime_checkable
class TrialVerifierArtifactPublisherPort(Protocol):
    """Publish one explicitly declared workload export across verifier isolation."""

    @property
    def identity_digest(self) -> str: ...

    def publish(
        self,
        *,
        request: TrialExecutionRequest,
        declaration: TaskArtifactSpec,
        payload: object,
    ) -> TaskVerifierArtifact: ...


class VerifierStageWorkloadTrialProvider:
    """Execute one Workload task and export only task-declared verifier artifacts."""

    def __init__(
        self,
        *,
        protocol_identity: object,
        workload: WorkloadTaskExecutionPort,
        task_projection: TrialTaskProjectionPort,
        measurement_projection: TrialMeasurementProjectionPort,
        artifact_publisher: TrialVerifierArtifactPublisherPort,
    ) -> None:
        digest = getattr(protocol_identity, "digest", None)
        if not callable(digest):
            raise TypeError(
                "verifier-stage workload provider requires protocol identity"
            )
        protocol_digest = digest()
        if type(protocol_digest) is not str or len(protocol_digest) != 64:
            raise TypeError(
                "verifier-stage workload protocol identity digest is invalid"
            )
        if not callable(getattr(workload, "execute_one", None)):
            raise TypeError(
                "verifier-stage workload provider requires WorkloadTaskExecutionPort"
            )
        if not isinstance(task_projection, TrialTaskProjectionPort):
            raise TypeError(
                "verifier-stage workload provider requires TrialTaskProjectionPort"
            )
        if not isinstance(
            measurement_projection,
            TrialMeasurementProjectionPort,
        ):
            raise TypeError(
                "verifier-stage workload provider requires TrialMeasurementProjectionPort"
            )
        if not isinstance(
            artifact_publisher,
            TrialVerifierArtifactPublisherPort,
        ):
            raise TypeError(
                "verifier-stage workload provider requires "
                "TrialVerifierArtifactPublisherPort"
            )
        if type(artifact_publisher.identity_digest) is not str or len(
            artifact_publisher.identity_digest
        ) != 64:
            raise TypeError(
                "verifier artifact publisher identity digest is invalid"
            )
        self.protocol_identity = protocol_identity
        self._workload = workload
        self._task_projection = task_projection
        self._measurement_projection = measurement_projection
        self._artifact_publisher = artifact_publisher
        self.identity_digest = canonical_digest(
            {
                "provider": "verifier-stage-workload-trial-provider.v1",
                "protocol_identity": protocol_digest,
                "task_projection": task_projection.identity_digest,
                "measurement_projection": measurement_projection.identity_digest,
                "artifact_publisher": artifact_publisher.identity_digest,
            }
        )

    def run_trial(
        self,
        request: TrialExecutionRequest,
    ) -> TrialExecutionStageReceipt:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError(
                "verifier-stage workload provider requires TrialExecutionRequest"
            )
        if request.protocol_identity != self.protocol_identity:
            raise ValueError("trial request protocol identity drift")
        if len(request.task_definitions) != 1:
            raise ValueError(
                "verifier-stage workload provider currently requires a "
                "single-node assignment workload"
            )
        task_definition = request.task_definitions[0]
        package = task_definition.package
        if package is None or package.verifier_requirement_id is None:
            raise ValueError(
                "verifier-stage workload provider requires task-declared verifier"
            )
        task_id = task_definition.task_id
        if request.assignment.workload.task_ids != (task_id,):
            raise ValueError(
                "verifier-stage workload provider assignment workload drifted"
            )
        task = self._task_projection.task(request, task_definition)
        if getattr(task, "task_id", None) != task_id:
            raise ValueError("projected workload task identity drift")
        context = ExecutionContext(
            run_id=request.run_id,
            trace_id=request.request_digest,
            span_id=f"trial:{request.assignment.assignment_digest[:16]}",
            study_id=request.assignment.study_id,
            condition_id=request.assignment.variant_id,
            condition_selections=tuple(
                (row.factor_id, row.level_id)
                for row in request.intervention_spec.selections
            ),
            task_id=task_id,
            operation_id=request.request_digest,
            component_id="verifier-stage-workload-trial-provider",
        )
        result = self._workload.execute_one(task, context)
        if not isinstance(result, WorkloadTaskResult):
            raise TypeError(
                "verifier-stage workload provider requires WorkloadTaskResult"
            )
        if result.task_id != task_id:
            raise ValueError("workload result task identity drift")
        if not result.success:
            raise RuntimeError(
                "workload execution failed before verifier handoff: "
                f"{result.failure_reason or 'unknown execution failure'}"
            )

        declared = {row.artifact_id: row for row in package.artifacts}
        exported = dict(result.exports)
        undeclared = tuple(sorted(set(exported) - set(declared)))
        if undeclared:
            raise ValueError(
                "workload attempted to export undeclared verifier artifacts: "
                f"{undeclared}"
            )
        missing = tuple(
            row.artifact_id
            for row in package.artifacts
            if row.required and row.artifact_id not in exported
        )
        if missing:
            raise ValueError(
                "workload is missing required verifier exports: "
                f"{missing}"
            )
        verifier_artifacts = tuple(
            self._artifact_publisher.publish(
                request=request,
                declaration=declaration,
                payload=exported[declaration.artifact_id],
            )
            for declaration in package.artifacts
            if declaration.artifact_id in exported
        )
        references = tuple(row.reference for row in verifier_artifacts)
        measurements = self._measurement_projection.project(request, result)
        for row in measurements:
            row.validate_against(request.measurement_protocol)
        return TrialExecutionStageReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
            verifier_artifacts=verifier_artifacts,
            evidence_refs=references,
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

    verifier_tasks = tuple(
        definition
        for definition in request.task_definitions
        if definition.package is not None
        and definition.package.verifier_requirement_id is not None
    )
    if len(verifier_tasks) > 1:
        raise ValueError(
            "trial receipt verifier validation requires per-node verifier receipts "
            "for multi-verifier workload graphs"
        )
    task = verifier_tasks[0] if verifier_tasks else None
    package = None if task is None else task.package
    verifier_required = task is not None
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
        final_by_id = {
            row.measurement_id: row for row in receipt.measurements
        }
        if len(final_by_id) != len(receipt.measurements):
            raise ValueError("trial measurements contain duplicate identities")
        for row in verifier.measurements:
            if final_by_id.get(row.measurement_id) != row:
                raise ValueError(
                    "verifier measurement is not preserved exactly in final receipt"
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

        verifier_tasks = tuple(
            definition
            for definition in request.task_definitions
            if definition.package is not None
            and definition.package.verifier_requirement_id is not None
        )
        if len(verifier_tasks) > 1:
            raise ValueError(
                "trial verifier orchestration requires per-node verifier "
                "receipts for multi-verifier workload graphs"
            )
        task = verifier_tasks[0] if verifier_tasks else None
        package = None if task is None else task.package
        verifier_required = task is not None
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

        stage_by_id = {
            row.measurement_id: row for row in provider_receipt.measurements
        }
        verifier_by_id = {
            row.measurement_id: row for row in verifier_receipt.measurements
        }
        if len(stage_by_id) != len(provider_receipt.measurements):
            raise ValueError("execution stage produced duplicate measurement identities")
        if len(verifier_by_id) != len(verifier_receipt.measurements):
            raise ValueError("verifier produced duplicate measurement identities")
        overlap = tuple(sorted(set(stage_by_id) & set(verifier_by_id)))
        if overlap:
            raise ValueError(
                "execution stage and verifier both own measurements: "
                + ", ".join(overlap)
            )
        combined = {**stage_by_id, **verifier_by_id}
        measurements = tuple(
            combined[definition.measurement_id]
            for definition in request.measurement_protocol.definitions
            if definition.measurement_id in combined
        )
        evidence_refs = tuple(
            dict.fromkeys(
                provider_receipt.evidence_refs + verifier_receipt.evidence_refs
            )
        )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
            evidence_refs=evidence_refs,
            verifier_receipt=verifier_receipt,
        )


__all__ = [
    "StandardWorkloadMeasurementProjection",
    "TrialVerifierArtifactPublisherPort",
    "TrialVerifierOrchestrator",
    "VerifierStageWorkloadTrialProvider",
    "WorkloadTrialProvider",
]
