"""Study-owned Trial provider, verifier, and measurement projection semantics."""
from __future__ import annotations
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_assignment_digest,
    study_assignment_text,
    study_assignment_repetition,
    study_assignment_workload,
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_digest,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    assignment_workload_task_ids,
    validate_assignment_workload,
    MeasurementContentReference,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    TaskVerifierArtifact,
    TaskVerifierPort,
    TaskVerifierReceipt,
    TaskVerifierRequest,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    TrialMeasurementProjectionPort,
)


from ..api.contracts import assignment_workload_task_ids
from ..api.unit_semantics import (
    execution_policy_budget,
    execution_policy_environment_seed_scope,
    execution_policy_environment_session_scope,
    execution_policy_replay_level,
    measurement_definitions,
    measurement_id,
    measurement_protocol_semantic_digest,
    measurement_schema_id,
    measurement_semantic_digest,
    measurement_value_kind,
    participant_schedule_waves,
    task_id,
    task_package,
    trial_protocol_digest,
)


from dataclasses import replace

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionControlPort
from noetrium_platform.research.execution.api import (
    ExecutionBudgetAuthorityPort,
    ExecutionBudgetPolicy,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadExecutionPort,
    WorkloadGraphResult,
    WorkloadTaskResult,
)


class _TrialScientificExecutionControl:
    """Project one activated ExecutionBudget scope into runtime control.

    The budget authority owns scientific wall-clock truth. This adapter only
    converts its live residual time into the concurrency Deadline vocabulary.
    """

    __slots__ = ("_parent", "_budget", "_scope_id")

    def __init__(
        self,
        parent: ExecutionControlPort,
        budget: ExecutionBudgetAuthorityPort,
        scope_id: str,
    ) -> None:
        if not isinstance(parent, ExecutionControlPort):
            raise TypeError("scientific control requires ExecutionControlPort")
        if not isinstance(budget, ExecutionBudgetAuthorityPort):
            raise TypeError("scientific control requires ExecutionBudgetAuthorityPort")
        if type(scope_id) is not str or not scope_id.strip():
            raise ValueError("scientific control requires scope_id")
        self._parent = parent
        self._budget = budget
        self._scope_id = scope_id

    @property
    def cancelled(self) -> bool:
        return self._parent.cancelled

    @property
    def reason(self) -> str | None:
        return self._parent.reason

    def _scientific_remaining_seconds(self) -> float | None:
        if not self.scientific_time_active:
            return None
        return self._budget.remaining_seconds(self._scope_id)

    @property
    def scientific_deadline(self) -> Deadline | None:
        remaining = self._scientific_remaining_seconds()
        if remaining is None:
            return None
        if remaining <= 0.0:
            # An expired immutable Deadline projection. Construction is direct
            # because Deadline.after() intentionally rejects non-positive input.
            import time
            return Deadline(time.monotonic())
        return Deadline.after(remaining)

    @property
    def remaining_seconds(self) -> float | None:
        parent_remaining = self._parent.remaining_seconds
        scientific_remaining = self._scientific_remaining_seconds()
        if parent_remaining is None:
            return scientific_remaining
        if scientific_remaining is None:
            return parent_remaining
        return max(0.0, min(parent_remaining, scientific_remaining))

    @property
    def deadline(self) -> Deadline | None:
        parent = self._parent.deadline
        scientific = self.scientific_deadline
        if parent is None:
            return scientific
        if scientific is None:
            return parent
        return (
            parent if parent.remaining_seconds <= scientific.remaining_seconds
            else scientific
        )

    @property
    def scientific_time_active(self) -> bool:
        return self._budget.snapshot(self._scope_id).scientific_time_active

    def activate_scientific_time(self) -> None:
        self._parent.checkpoint()
        self._budget.activate_scope(self._scope_id)

    def checkpoint(self) -> None:
        self._parent.checkpoint()
        if self.scientific_time_active:
            self._budget.require_active(self._scope_id)

    def subscribe_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        # The scientific wall-clock budget is a deadline, not a separate
        # cancellation authority. Forward the sole parent transition directly.
        return self._parent.subscribe_cancel(callback)

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("scientific control wait timeout cannot be negative")
        remaining = self.remaining_seconds
        bounded = timeout
        if remaining is not None:
            bounded = remaining if timeout is None else min(float(timeout), remaining)
        if self._parent.wait(bounded):
            return True
        self.checkpoint()
        return False


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
            "declared_source_reducers": ("sum", "mean", "last", "min", "max", "all", "any", "series"),
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
    def _source_exists(cls, row: WorkloadTaskResult, path: str) -> bool:
        try:
            cls._resolve_source(row, path)
        except KeyError:
            return False
        return True

    @classmethod
    def _censored_source_missing(
        cls, definition, rows: tuple[WorkloadTaskResult, ...],
    ) -> bool:
        """Do not turn unobserved task-side evidence into numeric zeros."""
        censored = tuple(
            row for row in rows
            if (
                row.diagnostics.get("scientific_censored") is True
                or (
                    not row.success
                    and not row.participant_receipts
                    and row.completion_receipt is None
                )
            )
        )
        source_path = definition.parameters.get("source_path")
        # Failed Methods may have attempted actions but lack final metric
        # exports. Preserve unobserved measurements as absent (never zero).
        if isinstance(source_path, str) and any(
            not row.success
            and not cls._source_exists(row, source_path)
            and any(
                getattr(receipt, "status", None) == "failed"
                for _role, receipt in row.participant_receipts
            )
            for row in rows
        ):
            return True
        # A failed participant can expose its last attempted action as
        # exports.participants.<role>.result, even though no final Method
        # result was produced. An action envelope is evidence of an attempt,
        # not authority for Method-level numeric measurements.
        if isinstance(source_path, str):
            segments = source_path.split(".")
            if (
                len(segments) >= 5
                and segments[:2] == ["exports", "participants"]
                and segments[3] == "result"
            ):
                parent_path = ".".join(segments[:4])
                if any(
                    not row.success
                    and not cls._source_exists(row, source_path)
                    and (
                        not cls._source_exists(row, parent_path)
                        or (
                            isinstance(cls._resolve_source(row, parent_path), Mapping)
                            and "action_type" in cls._resolve_source(row, parent_path)
                            and "payload" in cls._resolve_source(row, parent_path)
                        )
                    )
                    for row in rows
                ):
                    return True
        if not censored:
            return False
        if (
            source_path == "steps"
            or (
                source_path is None
                and definition.parameters.get("semantic_kind") == "steps"
            )
        ) and any(
            row.diagnostics.get("step_count_unobserved") is True
            or (not row.participant_receipts and row.completion_receipt is None)
            for row in censored
        ):
            return True
        return (
            source_path is not None
            and any(not cls._source_exists(row, source_path) for row in censored)
        )

    @classmethod
    def _declared_value(
        cls,
        definition,
        rows: tuple[WorkloadTaskResult, ...],
    ) -> MeasurementValue:
        path = definition.parameters.get("source_path")
        reducer = definition.parameters.get("reducer")
        if path is None:
            raise KeyError(measurement_id(definition))
        values_list = []
        for row in rows:
            try:
                value = cls._resolve_source(row, path)
            except KeyError:
                # A heterogeneous workload may produce a declared scientific
                # observation in only some task nodes. Its reducers operate on
                # the ordered emitting subsequence, not on unrelated tasks.
                continue
            values_list.append(value)
        values = tuple(values_list)
        if not values:
            raise KeyError(
                f"measurement {measurement_id(definition)!r} has no observed "
                f"source_path {path!r} in {len(rows)} workload task results"
            )
        resolved_reducer = reducer or "last"

        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
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

        if (
            MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SEQUENCE
            and resolved_reducer == "series"
        ):
            return MeasurementValue(
                MeasurementValueKind.SEQUENCE,
                sequence=tuple(values),
            )

        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.BOOLEAN:
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
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.CATEGORICAL:
            if type(value) is not str:
                raise TypeError("categorical measurement source must resolve text")
            return MeasurementValue(MeasurementValueKind.CATEGORICAL,categorical=value)
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.STRUCTURED:
            if not isinstance(value,Mapping):
                raise TypeError("structured measurement source must resolve an object")
            return MeasurementValue(MeasurementValueKind.STRUCTURED,structured=value)
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SEQUENCE:
            if isinstance(value,(str,bytes,bytearray)) or not isinstance(value,(tuple,list)):
                raise TypeError("sequence measurement source must resolve a sequence")
            return MeasurementValue(MeasurementValueKind.SEQUENCE,sequence=tuple(value))
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.DISTRIBUTION:
            if not isinstance(value,(tuple,list)):
                raise TypeError("distribution measurement source must resolve a sequence")
            return MeasurementValue(
                MeasurementValueKind.DISTRIBUTION,
                distribution=tuple(tuple(row) for row in value),
            )
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.MATRIX:
            if not isinstance(value,(tuple,list)):
                raise TypeError("matrix measurement source must resolve a sequence")
            return MeasurementValue(
                MeasurementValueKind.MATRIX,
                matrix=tuple(tuple(row) for row in value),
            )
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.TEXT_JUDGEMENT:
            if type(value) is not str:
                raise TypeError("text-judgement measurement source must resolve text")
            return MeasurementValue(
                MeasurementValueKind.TEXT_JUDGEMENT,
                text_judgement=value,
            )
        if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.CONTENT_REFERENCE:
            if type(value) is not MeasurementContentReference:
                raise TypeError(
                    "content-reference measurement source must resolve MeasurementContentReference"
                )
            return MeasurementValue(
                MeasurementValueKind.CONTENT_REFERENCE,
                content_reference=value,
            )
        raise ValueError(
            f"unsupported declared measurement value kind: {MeasurementValueKind(measurement_value_kind(definition)).value}"
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
        semantic = str(definition.parameters["semantic_kind"])
        if definition.parameters.get("source_path") is not None:
            return cls._declared_value(definition, rows)
        if semantic == "task_success":
            if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.BOOLEAN:
                return MeasurementValue(
                    MeasurementValueKind.BOOLEAN,
                    boolean=all(row.success for row in rows),
                )
            if MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
                return MeasurementValue(
                    MeasurementValueKind.SCALAR,
                    scalar=(
                        sum(1.0 for row in rows if row.success) / len(rows)
                    ),
                )
        elif semantic == "utility" and MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=sum(float(row.utility) for row in rows) / len(rows),
            )
        elif semantic == "steps" and MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=float(sum(row.steps for row in rows)),
            )
        elif semantic == "duration_seconds" and MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=float(sum(row.duration_s for row in rows)),
            )
        elif semantic == "blocked" and MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.BOOLEAN:
            return MeasurementValue(
                MeasurementValueKind.BOOLEAN,
                boolean=any(row.blocked for row in rows),
            )
        elif semantic == "resource_usage" and MeasurementValueKind(measurement_value_kind(definition)) is MeasurementValueKind.SCALAR:
            values = tuple(row.diagnostics.get(measurement_id(definition)) for row in rows)
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in values
            ):
                raise KeyError(
                    "workload result has no numeric resource-usage diagnostic "
                    f"{measurement_id(definition)!r}"
                )
            return MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=sum(float(value) for value in values),
            )
        raise ValueError(
            "standard workload measurement projection cannot represent "
            f"semantic_kind={semantic!r} as value_kind={MeasurementValueKind(measurement_value_kind(definition)).value!r}"
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
            task_package(definition) is not None
            and task_package(definition).get("verifier_requirement_id") is not None
            for definition in request.task_definitions
        )
        verifier_owned = frozenset({"task_success", "utility"})
        task_rows = (
            result.task_results if isinstance(result, WorkloadGraphResult)
            else (result,)
        )
        rows: list[MeasurementRecord] = []
        for definition in measurement_definitions(protocol):
            if (
                str(definition.parameters["semantic_kind"]) not in self._SUPPORTED
                and definition.parameters.get("source_path") is None
            ):
                continue
            if verifier_required and str(definition.parameters["semantic_kind"]) in verifier_owned:
                continue
            # Keep measured success, utility and elapsed time. Do not project
            # absent Method exports or unobserved step totals from censored
            # attempts as zeros, including in mixed workload graphs.
            if self._censored_source_missing(definition, task_rows):
                continue
            try:
                value = self._value(definition, result)
            except KeyError as exc:
                # A declared source without a single observed producer is an
                # incomplete Trial, not a missing/zero scientific measurement.
                raise ValueError(
                    f"Trial measurement {measurement_id(definition)!r} "
                    "has no authoritative workload source"
                ) from exc
            rows.append(MeasurementRecord(
                project_id=request.project_id,
                study_id=study_assignment_text(request.assignment, "study_id"),
                run_id=request.run_id,
                assignment_digest=study_assignment_digest(request.assignment),
                variant_id=study_assignment_text(request.assignment, "variant_id"),
                producer_id="noetrium.workload-trial-provider",
                producer_revision_digest=producer_revision,
                measurement_id=measurement_id(definition),
                schema_id=measurement_schema_id(definition),
                measurement_semantic_digest=measurement_semantic_digest(definition),
                measurement_protocol_semantic_digest=measurement_protocol_semantic_digest(protocol),
                value=value,
                logical_time=(
                    f"assignment:{study_assignment_repetition(request.assignment)}:"
                    f"{study_assignment_text(request.assignment, "seed")}:{measurement_id(definition)}"
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
        protocol_identity: NoetriumUnit,
        workload: WorkloadExecutionPort,
        measurement_projection: TrialMeasurementProjectionPort,
        execution_budget: ExecutionBudgetAuthorityPort,
        artifact_publisher: TrialVerifierArtifactPublisherPort | None = None,
        trial_preparer: Callable[[TrialExecutionRequest, ExecutionControlPort], None] | None = None,
        trial_finalizer: Callable[[TrialExecutionRequest], None] | None = None,
        lifecycle_identity_digest: str | None = None,
    ) -> None:
        if type(protocol_identity) is not NoetriumUnit:
            raise TypeError("workload trial provider requires trial protocol Unit")
        protocol_digest = trial_protocol_digest(protocol_identity)
        if not callable(getattr(workload, "execute_graph", None)) or not callable(
            getattr(workload, "execute_one", None)
        ):
            raise TypeError(
                "workload trial provider requires universal WorkloadExecutionPort"
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
            ("measurement projection", measurement_projection.identity_digest),
        ):
            if type(value) is not str or len(value) != 64:
                raise TypeError(f"{field_name} identity digest is invalid")
        self.protocol_identity = protocol_identity
        self._workload = workload
        self._measurement_projection = measurement_projection
        if not isinstance(execution_budget, ExecutionBudgetAuthorityPort):
            raise TypeError(
                "workload trial provider execution_budget must satisfy "
                "ExecutionBudgetAuthorityPort"
            )
        self._execution_budget = execution_budget
        self._artifact_publisher = artifact_publisher
        if trial_preparer is not None and not callable(trial_preparer):
            raise TypeError("workload trial provider trial_preparer must be callable")
        if trial_finalizer is not None and not callable(trial_finalizer):
            raise TypeError("workload trial provider trial_finalizer must be callable")
        if (trial_preparer is None and trial_finalizer is None) != (
            lifecycle_identity_digest is None
        ):
            raise ValueError(
                "trial lifecycle callbacks require one lifecycle_identity_digest"
            )
        if lifecycle_identity_digest is not None and (
            type(lifecycle_identity_digest) is not str
            or len(lifecycle_identity_digest) != 64
        ):
            raise ValueError("trial lifecycle identity must be SHA-256")
        self._trial_preparer = trial_preparer
        self._trial_finalizer = trial_finalizer
        self._lifecycle_identity_digest = lifecycle_identity_digest
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
                "provider": "workload-trial-provider.v5",
                "protocol_identity": protocol_digest,
                "workload": workload_identity,
                "measurement_projection": measurement_projection.identity_digest,
                "execution_budget": execution_budget.identity_digest,
                "artifact_publisher": (
                    None if artifact_publisher is None else artifact_publisher.identity_digest
                ),
                "lifecycle_identity_digest": lifecycle_identity_digest,
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

    @staticmethod
    def _budget_policy(request: TrialExecutionRequest) -> ExecutionBudgetPolicy:
        budget = execution_policy_budget(request.execution_policy)
        if budget is None:
            accounting_digest = canonical_digest({
                "schema": "noetrium.execution-usage-accounting.v1",
                "replay_level": execution_policy_replay_level(request.execution_policy).value,
            })
            return ExecutionBudgetPolicy(
                scope_id=request.assignment_lifetime_id,
                budget_id="no-scientific-budget",
                budget_digest=accounting_digest,
                replay_level=execution_policy_replay_level(request.execution_policy).value,
            )
        return ExecutionBudgetPolicy(
            scope_id=request.assignment_lifetime_id,
            budget_id=budget.unit_id,
            budget_digest=budget.unit_digest,
            replay_level=execution_policy_replay_level(request.execution_policy).value,
            max_steps=budget.parameters.get("max_steps"),
            max_seconds=budget.parameters.get("max_seconds"),
            max_tokens=budget.parameters.get("max_tokens"),
            resource_budget_digest=budget.parameters.get("resource_budget_digest"),
            max_turns=budget.parameters.get("max_turns"),
            max_messages=budget.parameters.get("max_messages"),
            max_model_calls=budget.parameters.get("max_model_calls"),
            max_working_seconds=budget.parameters.get("max_working_seconds"),
            max_cost_usd=budget.parameters.get("max_cost_usd"),
        )

    def prepare_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> None:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError("workload trial preparation requires TrialExecutionRequest")
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("workload trial preparation requires ExecutionControlPort")
        control.checkpoint()
        self._execution_budget.open_scope(self._budget_policy(request))
        if self._trial_preparer is not None:
            # The trial preparer is a readiness barrier. For embodied tasks it
            # returns only after the environment is physically ready, the actor
            # has spawned, and the initial control channel is usable. Platform
            # queue/admission/world-start latency is therefore excluded from
            # the scientific TrialBudget.
            self._trial_preparer(request, control)
            control.checkpoint()
            self._execution_budget.activate_scope(
                request.assignment_lifetime_id
            )
        control.checkpoint()

    def run_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt:
        try:
            return self._run_trial(request, control)
        finally:
            if self._trial_finalizer is not None:
                self._trial_finalizer(request)

    def _run_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError(
                "workload trial provider requires TrialExecutionRequest"
            )
        if request.protocol_identity != self.protocol_identity:
            raise ValueError("trial request protocol identity drift")
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("workload trial provider requires ExecutionControlPort")
        control.checkpoint()
        budget = execution_policy_budget(request.execution_policy)
        budget_snapshot = self._execution_budget.open_scope(
            self._budget_policy(request)
        )
        verifier_tasks = tuple(
            definition for definition in request.task_definitions
            if task_package(definition) is not None
            and task_package(definition).get("verifier_requirement_id") is not None
        )

        tasks = request.task_definitions
        expected_ids = assignment_workload_task_ids(study_assignment_workload(request.assignment))
        actual_ids = tuple(task_id(task) for task in tasks)
        if actual_ids != expected_ids:
            raise ValueError(
                "projected workload graph task identity/order drift"
            )

        context = replace(
            request.execution_context,
            run_id=request.run_id,
            experiment_id=request.experiment_id,
            trace_id=request.execution_context.trace_id,
            span_id=f"trial:{study_assignment_digest(request.assignment)[:16]}",
            parent_span_id=request.execution_context.span_id,
            study_id=study_assignment_text(request.assignment, "study_id"),
            condition_id=study_assignment_text(request.assignment, "variant_id"),
            condition_selections=tuple(
                (str(row.parameters["factor_id"]), str(row.parameters["level_id"]))
                for row in request.intervention_spec.members
            ),
            intervention_values=tuple(
                (str(row.parameters["factor_id"]), row.parameters["value"])
                for row in request.intervention_spec.members
            ),
            assignment_seed=study_assignment_text(request.assignment, "seed"),
            repetition=study_assignment_repetition(request.assignment),
            participant_schedule=(
                ()
                if request.participant_schedule_spec is None
                else participant_schedule_waves(request.participant_schedule_spec)
            ),
            replay_level=execution_policy_replay_level(request.execution_policy).value,
            trial_budget=(
                {}
                if budget is None
                else {
                    "budget_id": budget.unit_id,
                    "budget_digest": budget.unit_digest,
                    "max_steps": budget.parameters.get("max_steps"),
                    "max_seconds": budget.parameters.get("max_seconds"),
                    "max_tokens": budget.parameters.get("max_tokens"),
                    "resource_budget_digest": budget.parameters.get("resource_budget_digest"),
                    "max_turns": budget.parameters.get("max_turns"),
                    "max_messages": budget.parameters.get("max_messages"),
                    "max_model_calls": budget.parameters.get("max_model_calls"),
                    "max_working_seconds": budget.parameters.get("max_working_seconds"),
                    "max_cost_usd": budget.parameters.get("max_cost_usd"),
                }
            ),
            execution_policy_admission_digest=budget_snapshot.admission_digest,
            participant_context={
                "scientific_inputs": dict(request.scientific_inputs),
                "environment_session_scope": (
                    execution_policy_environment_session_scope(request.execution_policy)
                ),
                "environment_seed_scope": (
                    execution_policy_environment_seed_scope(request.execution_policy)
                ),
            },
            lifetime_id=request.assignment_lifetime_id,
            task_id=None,
            operation_id=request.request_digest,
            component_id="workload-trial-provider",
        )
        scientific_control = _TrialScientificExecutionControl(
            control,
            self._execution_budget,
            request.assignment_lifetime_id,
        )
        scientific_control.checkpoint()
        result = self._workload.execute_graph(
            tasks,
            study_assignment_workload(request.assignment),
            context,
            scientific_control,
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
        observed_ids = {m.measurement_id for m in measurements}
        unobserved_ids: tuple[str, ...] = ()
        if isinstance(self._measurement_projection, StandardWorkloadMeasurementProjection):
            unobserved_ids = tuple(
                measurement_id(definition)
                for definition in measurement_definitions(request.measurement_protocol)
                if measurement_id(definition) not in observed_ids
                and self._measurement_projection._censored_source_missing(
                    definition, result.task_results
                )
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
                unobserved_ids,
            )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=study_assignment_digest(request.assignment),
            measurements=measurements,
            evidence_refs=method_evidence_refs,
            unobserved_measurement_ids=unobserved_ids,
        )


    def _verifier_stage_from_graph(
        self,
        request: TrialExecutionRequest,
        result: WorkloadGraphResult,
        verifier_tasks: tuple[object, ...],
        measurements: tuple[MeasurementRecord, ...],
        method_evidence_refs: tuple,
        unobserved_ids: tuple[str, ...],
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
        package = task_package(task_definition)
        if package is None or package.get("verifier_requirement_id") is None:
            raise ValueError(
                "workload trial provider requires task-declared verifier"
            )
        task_id_value = task_id(task_definition)
        matches = tuple(
            row for row in result.task_results
            if row.task_id == task_id_value
        )
        if len(matches) != 1:
            raise ValueError(
                "verifier task does not have one exact WorkloadGraph result"
            )
        task_result = matches[0]
        if not task_result.complete:
            raise RuntimeError(
                "workload graph verifier task did not complete before verifier handoff: "
                f"{task_result.failure_reason or 'unknown execution failure'}"
            )

        declared = {
            str(row["artifact_id"]): row
            for row in package.get("artifacts", ())
        }
        exported = dict(task_result.exports)
        undeclared = tuple(sorted(set(exported) - set(declared)))
        if undeclared:
            raise ValueError(
                "workload attempted to export undeclared verifier artifacts: "
                f"{undeclared}"
            )
        missing = tuple(
            str(row["artifact_id"])
            for row in package.get("artifacts", ())
            if bool(row.get("required", True))
            and str(row["artifact_id"]) not in exported
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
                payload=exported[str(declaration["artifact_id"])],
            )
            for declaration in package.get("artifacts", ())
            if str(declaration["artifact_id"]) in exported
        )
        references = tuple(
            dict.fromkeys(
                method_evidence_refs
                + tuple(row.reference for row in verifier_artifacts)
            )
        )
        return TrialExecutionStageReceipt(
            request_digest=request.request_digest,
            assignment_digest=study_assignment_digest(request.assignment),
            measurements=measurements,
            verifier_artifacts=verifier_artifacts,
            evidence_refs=references,
            unobserved_measurement_ids=unobserved_ids,
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
        declaration: Mapping[str, object],
        payload: object,
    ) -> TaskVerifierArtifact: ...




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
        if provider_receipt.assignment_digest != study_assignment_digest(request.assignment):
            raise ValueError("trial provider receipt does not bind the assignment")

        verifier_tasks = tuple(
            definition
            for definition in request.task_definitions
            if task_package(definition) is not None
            and task_package(definition).get("verifier_requirement_id") is not None
        )
        if len(verifier_tasks) > 1:
            raise ValueError(
                "trial verifier orchestration requires per-node verifier "
                "receipts for multi-verifier workload graphs"
            )
        task = verifier_tasks[0] if verifier_tasks else None
        package = None if task is None else task_package(task)
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
                unobserved_measurement_ids=provider_receipt.unobserved_measurement_ids,
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
            combined[measurement_id(definition)]
            for definition in measurement_definitions(request.measurement_protocol)
            if measurement_id(definition) in combined
        )
        evidence_refs = tuple(
            dict.fromkeys(
                provider_receipt.evidence_refs + verifier_receipt.evidence_refs
            )
        )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=study_assignment_digest(request.assignment),
            measurements=measurements,
            evidence_refs=evidence_refs,
            verifier_receipt=verifier_receipt,
            unobserved_measurement_ids=provider_receipt.unobserved_measurement_ids,
        )


__all__ = [
    "StandardWorkloadMeasurementProjection",
    "TrialVerifierArtifactPublisherPort",
    "TrialVerifierOrchestrator",
    "WorkloadTrialProvider",
]
