"""Study-owned Trial provider, verifier, and measurement projection semantics."""

from __future__ import annotations

from dataclasses import replace

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.api import (
    ExecutionBudgetAuthorityPort,
    ExecutionBudgetPolicy,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementContentReference,
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
    WorkloadExecutionPort,
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
            "projection": "standard-workload-measurements.v3",
            "semantic_kinds": tuple(sorted(self._SUPPORTED)),
            "declared_source_reducers": ("sum", "mean", "last", "min", "max", "all", "any"),
        })

    @staticmethod
    def _resolve_source(row: WorkloadTaskResult, path: str):
        value: object = row
        for part in path.split("."):
            if isinstance(value, Mapping):
                if part not in value:
                    raise KeyError(path)
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                raise KeyError(path)
        return value

    @classmethod
    def _declared_value(
        cls,
        definition,
        rows: tuple[WorkloadTaskResult, ...],
    ) -> MeasurementValue:
        path = definition.source_path
        reducer = definition.reducer
        if path is None:
            raise KeyError(definition.measurement_id)
        values = tuple(cls._resolve_source(row, path) for row in rows)
        if not values:
            raise ValueError("measurement source resolved no workload values")
        resolved_reducer = reducer or "last"

        if definition.value_kind is MeasurementValueKind.SCALAR:
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
                # Booleans are valid numeric sources only for mean/sum rates/counts.
                if not all(type(value) is bool for value in values):
                    raise TypeError(
                        f"measurement source {path!r} must resolve homogeneous numeric values"
                    )
                numbers = tuple(1.0 if value else 0.0 for value in values)
            else:
                numbers = tuple(float(value) for value in values)
            if resolved_reducer == "sum":
                scalar = sum(numbers)
            elif resolved_reducer == "mean":
                scalar = sum(numbers) / len(numbers)
            elif resolved_reducer == "last":
                scalar = numbers[-1]
            elif resolved_reducer == "min":
                scalar = min(numbers)
            elif resolved_reducer == "max":
                scalar = max(numbers)
            else:
                raise ValueError(
                    f"scalar measurement reducer {resolved_reducer!r} is unsupported"
                )
            return MeasurementValue(MeasurementValueKind.SCALAR, scalar=scalar)

        if definition.value_kind is MeasurementValueKind.BOOLEAN:
            if any(type(value) is not bool for value in values):
                raise TypeError(
                    f"boolean measurement source {path!r} must resolve bool values"
                )
            if resolved_reducer == "all":
                boolean = all(values)
            elif resolved_reducer == "any":
                boolean = any(values)
            elif resolved_reducer == "last":
                boolean = values[-1]
            else:
                raise ValueError(
                    f"boolean measurement reducer {resolved_reducer!r} is unsupported"
                )
            return MeasurementValue(MeasurementValueKind.BOOLEAN, boolean=boolean)

        if resolved_reducer != "last":
            raise ValueError(
                "non-scalar/non-boolean source measurements use reducer='last'; "
                "statistical aggregation belongs to the derived Metric/Analysis layer"
            )
        value=values[-1]
        if definition.value_kind is MeasurementValueKind.CATEGORICAL:
            if type(value) is not str:
                raise TypeError("categorical measurement source must resolve text")
            return MeasurementValue(MeasurementValueKind.CATEGORICAL,categorical=value)
        if definition.value_kind is MeasurementValueKind.STRUCTURED:
            if not isinstance(value,Mapping):
                raise TypeError("structured measurement source must resolve an object")
            return MeasurementValue(MeasurementValueKind.STRUCTURED,structured=value)
        if definition.value_kind is MeasurementValueKind.SEQUENCE:
            if isinstance(value,(str,bytes,bytearray)) or not isinstance(value,(tuple,list)):
                raise TypeError("sequence measurement source must resolve a sequence")
            return MeasurementValue(MeasurementValueKind.SEQUENCE,sequence=tuple(value))
        if definition.value_kind is MeasurementValueKind.DISTRIBUTION:
            if not isinstance(value,(tuple,list)):
                raise TypeError("distribution measurement source must resolve a sequence")
            return MeasurementValue(
                MeasurementValueKind.DISTRIBUTION,
                distribution=tuple(tuple(row) for row in value),
            )
        if definition.value_kind is MeasurementValueKind.MATRIX:
            if not isinstance(value,(tuple,list)):
                raise TypeError("matrix measurement source must resolve a sequence")
            return MeasurementValue(
                MeasurementValueKind.MATRIX,
                matrix=tuple(tuple(row) for row in value),
            )
        if definition.value_kind is MeasurementValueKind.TEXT_JUDGEMENT:
            if type(value) is not str:
                raise TypeError("text-judgement measurement source must resolve text")
            return MeasurementValue(
                MeasurementValueKind.TEXT_JUDGEMENT,
                text_judgement=value,
            )
        if definition.value_kind is MeasurementValueKind.CONTENT_REFERENCE:
            if type(value) is not MeasurementContentReference:
                raise TypeError(
                    "content-reference measurement source must resolve MeasurementContentReference"
                )
            return MeasurementValue(
                MeasurementValueKind.CONTENT_REFERENCE,
                content_reference=value,
            )
        raise ValueError(
            f"unsupported declared measurement value kind: {definition.value_kind.value}"
        )

    @classmethod
    def _value(
        cls,
        definition,
        result: WorkloadTaskResult | WorkloadGraphResult,
    ) -> MeasurementValue:
        rows = (
            result.task_results
            if isinstance(result, WorkloadGraphResult)
            else (result,)
        )
        semantic = definition.semantic_kind
        if definition.source_path is not None:
            return cls._declared_value(definition, rows)
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
            if (
                definition.semantic_kind not in self._SUPPORTED
                and definition.source_path is None
            ):
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
        workload: WorkloadExecutionPort,
        task_projection: TrialTaskProjectionPort,
        measurement_projection: TrialMeasurementProjectionPort,
        execution_budget: ExecutionBudgetAuthorityPort,
        artifact_publisher: TrialVerifierArtifactPublisherPort | None = None,
    ) -> None:
        digest = getattr(protocol_identity, "digest", None)
        if not callable(digest):
            raise TypeError("workload trial provider requires protocol identity")
        protocol_digest = digest()
        if type(protocol_digest) is not str or len(protocol_digest) != 64:
            raise TypeError("workload trial protocol identity digest is invalid")
        if not callable(getattr(workload, "execute_graph", None)) or not callable(
            getattr(workload, "execute_one", None)
        ):
            raise TypeError(
                "workload trial provider requires universal WorkloadExecutionPort"
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
        workload_identity = getattr(workload, "identity_digest", None)
        for field_name, value in (
            ("workload", workload_identity),
            ("task projection", task_projection.identity_digest),
            ("measurement projection", measurement_projection.identity_digest),
        ):
            if type(value) is not str or len(value) != 64:
                raise TypeError(f"{field_name} identity digest is invalid")
        self.protocol_identity = protocol_identity
        self._workload = workload
        self._task_projection = task_projection
        self._measurement_projection = measurement_projection
        if not isinstance(execution_budget, ExecutionBudgetAuthorityPort):
            raise TypeError(
                "workload trial provider execution_budget must satisfy "
                "ExecutionBudgetAuthorityPort"
            )
        self._execution_budget = execution_budget
        self._artifact_publisher = artifact_publisher
        if artifact_publisher is not None:
            if not isinstance(artifact_publisher, TrialVerifierArtifactPublisherPort):
                raise TypeError(
                    "workload trial provider artifact_publisher must satisfy "
                    "TrialVerifierArtifactPublisherPort"
                )
            if type(artifact_publisher.identity_digest) is not str or len(
                artifact_publisher.identity_digest
            ) != 64:
                raise TypeError("verifier artifact publisher identity digest is invalid")
        self.identity_digest = canonical_digest(
            {
                "provider": "workload-trial-provider.v4",
                "protocol_identity": protocol_digest,
                "workload": workload_identity,
                "task_projection": task_projection.identity_digest,
                "measurement_projection": measurement_projection.identity_digest,
                "execution_budget": execution_budget.identity_digest,
                "artifact_publisher": (
                    None if artifact_publisher is None else artifact_publisher.identity_digest
                ),
            }
        )

    @staticmethod
    def _method_evidence_refs(
        result: WorkloadGraphResult,
    ) -> tuple:
        references = tuple(
            receipt.evidence_reference
            for row in result.task_results
            for _role, receipt in row.participant_receipts
            if receipt.evidence_reference is not None
        )
        if len(references) != len(set(references)):
            references = tuple(dict.fromkeys(references))
        return references

    def run_trial(
        self,
        request: TrialExecutionRequest,
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError(
                "workload trial provider requires TrialExecutionRequest"
            )
        if request.protocol_identity != self.protocol_identity:
            raise ValueError("trial request protocol identity drift")
        budget = request.execution_policy.trial_budget
        budget_snapshot = self._execution_budget.open_scope(
            ExecutionBudgetPolicy(
                scope_id=request.assignment_lifetime_id,
                budget_id=budget.budget_id,
                budget_digest=budget.budget_digest,
                replay_level=request.execution_policy.replay_level.value,
                max_steps=budget.max_steps,
                max_seconds=budget.max_seconds,
                max_tokens=budget.max_tokens,
                resource_budget_digest=budget.resource_budget_digest,
                max_turns=budget.max_turns,
                max_messages=budget.max_messages,
                max_model_calls=budget.max_model_calls,
                max_working_seconds=budget.max_working_seconds,
                max_cost_usd=budget.max_cost_usd,
            )
        )
        verifier_tasks = tuple(
            definition for definition in request.task_definitions
            if definition.package is not None
            and definition.package.verifier_requirement_id is not None
        )

        raw_tasks = tuple(
            self._task_projection.task(request, definition)
            for definition in request.task_definitions
        )
        time_limits = tuple(
            value
            for value in (
                budget.max_seconds,
                budget.max_working_seconds,
            )
            if value is not None
        )
        task_deadline = None if not time_limits else min(time_limits)
        tasks = tuple(
            replace(
                task,
                max_steps=(
                    task.max_steps
                    if budget.max_steps is None
                    else min(task.max_steps, budget.max_steps)
                ),
                max_seconds=(
                    task.max_seconds
                    if task_deadline is None
                    else min(task.max_seconds, float(task_deadline))
                ),
            )
            for task in raw_tasks
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
            execution_tenant_id=request.project_id,
            condition_selections=tuple(
                (row.factor_id, row.level_id)
                for row in request.intervention_spec.selections
            ),
            intervention_values=tuple(
                (row.factor_id, row.value)
                for row in request.intervention_spec.selections
            ),
            assignment_seed=request.assignment.seed,
            repetition=request.assignment.repetition,
            participant_schedule=(
                ()
                if request.participant_schedule_spec is None
                else request.participant_schedule_spec.waves
            ),
            replay_level=request.execution_policy.replay_level.value,
            trial_budget={
                "budget_id": request.execution_policy.trial_budget.budget_id,
                "budget_digest": request.execution_policy.trial_budget.budget_digest,
                "max_steps": request.execution_policy.trial_budget.max_steps,
                "max_seconds": request.execution_policy.trial_budget.max_seconds,
                "max_tokens": request.execution_policy.trial_budget.max_tokens,
                "resource_budget_digest": (
                    request.execution_policy.trial_budget.resource_budget_digest
                ),
                "max_turns": request.execution_policy.trial_budget.max_turns,
                "max_messages": request.execution_policy.trial_budget.max_messages,
                "max_model_calls": request.execution_policy.trial_budget.max_model_calls,
                "max_working_seconds": (
                    request.execution_policy.trial_budget.max_working_seconds
                ),
                "max_cost_usd": request.execution_policy.trial_budget.max_cost_usd,
            },
            execution_policy_admission_digest=budget_snapshot.admission_digest,
            lifetime_id=request.assignment_lifetime_id,
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
        method_evidence_refs = self._method_evidence_refs(result)
        if verifier_tasks:
            return self._verifier_stage_from_graph(
                request,
                result,
                verifier_tasks,
                measurements,
                method_evidence_refs,
            )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
            evidence_refs=method_evidence_refs,
        )


    def _verifier_stage_from_graph(
        self,
        request: TrialExecutionRequest,
        result: WorkloadGraphResult,
        verifier_tasks: tuple[object, ...],
        measurements: tuple[MeasurementRecord, ...],
        method_evidence_refs: tuple,
    ) -> TrialExecutionStageReceipt:
        if len(verifier_tasks) != 1:
            raise ValueError(
                "one Trial currently admits exactly one verifier-backed task; "
                "multi-verifier receipts require a typed per-task verifier aggregate"
            )
        if self._artifact_publisher is None:
            raise ValueError(
                "verifier-backed task requires verifier artifact publisher authority"
            )
        task_definition = verifier_tasks[0]
        package = task_definition.package
        if package is None or package.verifier_requirement_id is None:
            raise ValueError(
                "workload trial provider requires task-declared verifier"
            )
        task_id = task_definition.task_id
        matches = tuple(
            row for row in result.task_results
            if row.task_id == task_id
        )
        if len(matches) != 1:
            raise ValueError(
                "verifier task does not have one exact WorkloadGraph result"
            )
        task_result = matches[0]
        if not task_result.success:
            raise RuntimeError(
                "workload graph verifier task failed before verifier handoff: "
                f"{task_result.failure_reason or 'unknown execution failure'}"
            )

        declared = {row.artifact_id: row for row in package.artifacts}
        exported = dict(task_result.exports)
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
        references = tuple(
            dict.fromkeys(
                method_evidence_refs
                + tuple(row.reference for row in verifier_artifacts)
            )
        )
        return TrialExecutionStageReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=measurements,
            verifier_artifacts=verifier_artifacts,
            evidence_refs=references,
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
    "WorkloadTrialProvider",
]
