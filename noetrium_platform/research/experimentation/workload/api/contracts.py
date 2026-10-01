from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
import math

from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    ExperimentWorkloadFailure,
    FailureScope,
    TaskDefinition,
    TrialExecutionRequest,
)
from noetrium_platform.research.execution.api import (
    ArtifactReference,
    MethodProgram,
    MethodRuntimeContext,
    ScopeIdentity,
    ScopeKind,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
)


@dataclass(frozen=True, slots=True)
class WorkloadCompletionReceipt:
    completion_key: str
    method_generation: str | None = None
    artifacts: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        if type(self.completion_key) is not str or not self.completion_key.strip():
            raise ValueError("workload completion_key must be non-empty")
        if self.method_generation is not None and (type(self.method_generation) is not str or not self.method_generation.strip()):
            raise ValueError("workload method_generation must be non-empty or None")
        if type(self.artifacts) is not tuple or any(type(v) is not str or not v.strip() for v in self.artifacts):
            raise ValueError("workload completion artifacts must be non-empty strings")
        if len(self.artifacts) != len(set(self.artifacts)):
            raise ValueError("workload completion artifacts must be unique")


@dataclass(frozen=True, slots=True)
class WorkloadMethodReceipt:
    run_id: str
    program_digest: str
    run_digest: str
    status: str
    step_count: int
    evidence_status: str
    evidence_reference: ArtifactReference | None = None
    failure_id: str | None = None
    def __post_init__(self) -> None:
        if any(type(v) is not str or not v.strip() for v in (self.run_id, self.status, self.evidence_status)):
            raise ValueError("workload method receipt identity/status fields are required")
        for name in ("program_digest", "run_digest"):
            value = getattr(self, name)
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise ValueError(f"workload method receipt {name} must be SHA-256 hex")
        if type(self.step_count) is not int or isinstance(self.step_count, bool) or self.step_count < 0:
            raise ValueError("workload method receipt step_count must be non-negative integer")
        if self.evidence_reference is not None and type(
            self.evidence_reference
        ) is not ArtifactReference:
            raise TypeError(
                "workload method receipt evidence_reference must be ArtifactReference or null"
            )
        if self.failure_id is not None and (
            type(self.failure_id) is not str or not self.failure_id.strip()
        ):
            raise ValueError("workload method receipt failure_id must be non-empty text or null")


def _freeze_mapping(value: Mapping[str, JsonValue], *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{field_name} must freeze to a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class WorkloadEvaluation:
    success: bool
    utility: float
    failure_reason: str = ""
    completion_receipt: WorkloadCompletionReceipt | None = None
    failure_scope: str = FailureScope.TASK.value
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)
    exports: Mapping[str, JsonValue] = field(default_factory=dict)
    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise TypeError("workload evaluation success must be bool")
        if isinstance(self.utility, bool) or not isinstance(self.utility, (int, float)) or not math.isfinite(float(self.utility)):
            raise ValueError("workload evaluation utility must be finite")
        if type(self.failure_reason) is not str or type(self.failure_scope) is not str:
            raise TypeError("workload evaluation failure fields must be strings")
        if self.success and self.failure_reason:
            raise ValueError("successful workload evaluation cannot carry failure_reason")
        if not self.success and not self.failure_reason.strip():
            raise ValueError("failed workload evaluation requires failure_reason")
        FailureScope(self.failure_scope)
        if self.completion_receipt is not None and not isinstance(self.completion_receipt, WorkloadCompletionReceipt):
            raise TypeError("workload completion_receipt must be WorkloadCompletionReceipt")
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, field_name="workload evaluation diagnostics"))
        object.__setattr__(self, "exports", _freeze_mapping(self.exports, field_name="workload evaluation exports"))


@dataclass(frozen=True, slots=True)
class WorkloadMethodInvocation:
    program: MethodProgram
    runtime: MethodRuntimeContext
    input_value: JsonValue = None
    initial_state: JsonObject | None = None
    resume: bool = False
    def __post_init__(self) -> None:
        if not isinstance(self.program, MethodProgram):
            raise TypeError("workload invocation program must be MethodProgram")
        if not isinstance(self.runtime, MethodRuntimeContext):
            raise TypeError("workload invocation runtime must be MethodRuntimeContext")
        if self.initial_state is not None and not isinstance(self.initial_state, Mapping):
            raise TypeError("workload invocation initial_state must be mapping or None")
        if type(self.resume) is not bool:
            raise TypeError("workload invocation resume must be bool")


@dataclass(frozen=True, slots=True)
class WorkloadTaskResult:
    task_id: str
    family: str
    success: bool
    utility: float
    steps: int
    duration_s: float
    lineage_id: str
    failure_reason: str = ""
    participant_receipts: tuple[tuple[str, WorkloadMethodReceipt], ...] = ()
    completion_receipt: WorkloadCompletionReceipt | None = None
    blocked: bool = False
    failure_scope: str = FailureScope.TASK.value
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)
    exports: Mapping[str, JsonValue] = field(default_factory=dict)
    _payload_cache: JsonObject | None = field(
        init=False,
        default=None,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )
    def __post_init__(self) -> None:
        if any(type(v) is not str or not v.strip() for v in (self.task_id, self.family, self.lineage_id, self.failure_scope)):
            raise ValueError("workload task result identity/scope fields are required")
        if type(self.failure_reason) is not str or type(self.success) is not bool or type(self.blocked) is not bool:
            raise TypeError("workload task result status fields are invalid")
        if type(self.steps) is not int or isinstance(self.steps, bool) or self.steps < 0:
            raise ValueError("workload task result steps must be non-negative integer")
        for name in ("utility", "duration_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"workload task result {name} must be finite")
        if self.duration_s < 0:
            raise ValueError("workload task result duration_s cannot be negative")
        FailureScope(self.failure_scope)
        if self.success and (self.blocked or self.failure_reason):
            raise ValueError("successful workload task result cannot be blocked or failed")
        if not self.success and not self.failure_reason.strip():
            raise ValueError("failed/blocked workload task result requires failure_reason")
        if type(self.participant_receipts) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or not row[0].strip()
            or not isinstance(row[1], WorkloadMethodReceipt)
            for row in self.participant_receipts
        ):
            raise TypeError(
                "workload participant_receipts must be (role, WorkloadMethodReceipt) pairs"
            )
        roles = tuple(row[0] for row in self.participant_receipts)
        if len(roles) != len(set(roles)):
            raise ValueError("workload participant receipt roles must be unique")
        if self.participant_receipts != tuple(
            sorted(self.participant_receipts, key=lambda row: row[0])
        ):
            raise ValueError("workload participant receipts must be canonically role-sorted")
        if self.completion_receipt is not None and not isinstance(self.completion_receipt, WorkloadCompletionReceipt):
            raise TypeError("workload completion_receipt must be WorkloadCompletionReceipt")
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, field_name="workload diagnostics"))
        object.__setattr__(self, "exports", _freeze_mapping(self.exports, field_name="workload exports"))


@dataclass(frozen=True, slots=True)
class WorkloadGraphResult:
    task_results: tuple[WorkloadTaskResult, ...]
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.task_results) is not tuple or not self.task_results:
            raise TypeError("workload graph result requires a non-empty task tuple")
        if any(not isinstance(row, WorkloadTaskResult) for row in self.task_results):
            raise TypeError("workload graph result must contain WorkloadTaskResult")
        task_ids = tuple(row.task_id for row in self.task_results)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("workload graph result task ids must be unique")
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "task_results": tuple(
                    workload_task_result_payload(row)
                    for row in self.task_results
                ),
            }),
        )

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(row.task_id for row in self.task_results)

    @property
    def steps_total(self) -> int:
        return sum(row.steps for row in self.task_results)

    @property
    def duration_s_total(self) -> float:
        return sum(row.duration_s for row in self.task_results)


@dataclass(frozen=True, slots=True)
class TaskDefinitionExperimentTaskProjection:
    """Project canonical Study TaskDefinition content into ExperimentTaskSpec."""

    _cache: SingleFlightCache[ExperimentTaskSpec] = field(
        default_factory=lambda: SingleFlightCache(max_entries=16384),
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "projection": "task-definition-experiment-task.v1",
            "content_schema": "objective|goal,context,max_steps,max_seconds",
        })

    def task(
        self,
        request: TrialExecutionRequest,
        definition: TaskDefinition,
    ) -> ExperimentTaskSpec:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError("task-definition projection requires TrialExecutionRequest")
        if not isinstance(definition, TaskDefinition):
            raise TypeError("task-definition projection requires TaskDefinition")
        workload = request.assignment.workload
        try:
            definition_index = workload.task_index(definition.task_id)
        except KeyError as exc:
            raise ValueError(
                "task-definition projection definition is outside assignment workload"
            ) from exc
        if request.task_definitions[definition_index] != definition:
            raise ValueError(
                "task-definition projection definition identity drift"
            )
        cache_key = canonical_digest({
            "task_digest": definition.task_digest,
            "workload_digest": workload.workload_digest,
        })

        def build() -> ExperimentTaskSpec:
            content = definition.content
            if not isinstance(content, Mapping):
                raise ValueError(
                    "task-definition projection requires inline immutable task content"
                )
            objective = content.get("objective", content.get("goal"))
            if type(objective) is not str or not objective.strip():
                raise ValueError(
                    f"task {definition.task_id!r} content requires objective or goal"
                )
            context = content.get("context", "")
            if type(context) is not str:
                raise TypeError("task-definition projection context must be text")
            depends_on = workload.prerequisites_for(definition.task_id)
            retry_edges = workload.retry_sources_for(definition.task_id)
            if len(retry_edges) > 1:
                raise ValueError(
                    "task-definition projection admits at most one retry source"
                )
            return ExperimentTaskSpec(
                task_id=definition.task_id,
                family=definition.family,
                objective=objective.strip(),
                context=context,
                lineage_id=(
                    definition.lineage_refs[0]
                    if definition.lineage_refs
                    else definition.task_id
                ),
                depends_on_task_ids=depends_on,
                retry_of_task_id=(retry_edges[0] if retry_edges else None),
                max_steps=content.get("max_steps"),
                max_seconds=content.get("max_seconds"),
                payload=content,
            )

        return self._cache.get_or_create(cache_key, build)


@dataclass(frozen=True, slots=True)
class StaticExperimentTaskProjection:
    """Study-agnostic lookup over already-authored ExperimentTaskSpec values."""

    tasks: tuple[ExperimentTaskSpec, ...]
    _tasks_by_id: Mapping[str, ExperimentTaskSpec] = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    def __post_init__(self) -> None:
        if type(self.tasks) is not tuple or not self.tasks:
            raise TypeError("static task projection requires a non-empty task tuple")
        if any(not isinstance(row, ExperimentTaskSpec) for row in self.tasks):
            raise TypeError("static task projection tasks must be ExperimentTaskSpec")
        ids = tuple(row.task_id for row in self.tasks)
        if len(ids) != len(set(ids)):
            raise ValueError("static task projection task ids must be unique")
        object.__setattr__(
            self,
            "_tasks_by_id",
            MappingProxyType({
                row.task_id: row
                for row in self.tasks
            }),
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "projection": "static-experiment-task.v1",
            "tasks": self.tasks,
        })

    def task(
        self,
        request: TrialExecutionRequest,
        definition: TaskDefinition,
    ) -> ExperimentTaskSpec:
        if not isinstance(request, TrialExecutionRequest):
            raise TypeError(
                "static task projection requires TrialExecutionRequest"
            )
        if not isinstance(definition, TaskDefinition):
            raise TypeError("static task projection requires TaskDefinition")
        workload = request.assignment.workload
        task_id = definition.task_id
        try:
            definition_index = workload.task_index(task_id)
        except KeyError as exc:
            raise ValueError(
                "static task projection definition is outside assignment workload"
            ) from exc
        if request.task_definitions[definition_index] != definition:
            raise ValueError("static task projection definition identity drift")
        try:
            return self._tasks_by_id[task_id]
        except KeyError as exc:
            raise KeyError(
                f"static task projection has no unique task {task_id!r}"
            ) from exc


def _artifact_reference_payload(
    reference: ArtifactReference | None,
) -> JsonValue:
    if reference is None:
        return None
    return {
        "reference_id": reference.reference_id,
        "scope_kind": reference.scope.kind.value,
        "scope_id": reference.scope.scope_id,
        "artifact_id": reference.artifact_id,
        "generation": reference.generation,
    }


def _artifact_reference_from_payload(payload: JsonValue) -> ArtifactReference | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise TypeError("workload artifact reference payload must be an object")
    return ArtifactReference(
        str(payload["reference_id"]),
        ScopeIdentity(
            ScopeKind(str(payload["scope_kind"])),
            str(payload["scope_id"]),
        ),
        str(payload["artifact_id"]),
        int(payload["generation"]),
    )


def workload_method_receipt_payload(
    receipt: WorkloadMethodReceipt,
) -> JsonObject:
    if not isinstance(receipt, WorkloadMethodReceipt):
        raise TypeError("workload method receipt payload requires WorkloadMethodReceipt")
    frozen = freeze_json({
        "run_id": receipt.run_id,
        "program_digest": receipt.program_digest,
        "run_digest": receipt.run_digest,
        "status": receipt.status,
        "step_count": receipt.step_count,
        "evidence_status": receipt.evidence_status,
        "evidence_reference": _artifact_reference_payload(
            receipt.evidence_reference
        ),
        "failure_id": receipt.failure_id,
    })
    if not isinstance(frozen, Mapping):
        raise TypeError("workload method receipt payload must freeze to object")
    return frozen


def workload_method_receipt_from_payload(
    payload: JsonValue,
) -> WorkloadMethodReceipt:
    if not isinstance(payload, Mapping):
        raise TypeError("workload method receipt payload must be an object")
    return WorkloadMethodReceipt(
        run_id=str(payload["run_id"]),
        program_digest=str(payload["program_digest"]),
        run_digest=str(payload["run_digest"]),
        status=str(payload["status"]),
        step_count=int(payload["step_count"]),
        evidence_status=str(payload["evidence_status"]),
        evidence_reference=_artifact_reference_from_payload(
            payload.get("evidence_reference")
        ),
        failure_id=(
            None
            if payload.get("failure_id") is None
            else str(payload["failure_id"])
        ),
    )


def workload_task_result_payload(result: WorkloadTaskResult) -> JsonObject:
    if not isinstance(result, WorkloadTaskResult):
        raise TypeError("workload result payload requires WorkloadTaskResult")
    cached = result._payload_cache
    if cached is not None:
        return cached
    completion = result.completion_receipt
    payload = {
        "task_id": result.task_id,
        "family": result.family,
        "success": result.success,
        "utility": float(result.utility),
        "steps": result.steps,
        "duration_s": float(result.duration_s),
        "lineage_id": result.lineage_id,
        "failure_reason": result.failure_reason,
        "blocked": result.blocked,
        "failure_scope": result.failure_scope,
        "diagnostics": result.diagnostics,
        "exports": result.exports,
        "participant_receipts": tuple(
            {
                "role": role,
                "receipt": workload_method_receipt_payload(method),
            }
            for role, method in result.participant_receipts
        ),
        "completion_receipt": (
            None
            if completion is None
            else {
                "completion_key": completion.completion_key,
                "method_generation": completion.method_generation,
                "artifacts": completion.artifacts,
            }
        ),
    }
    frozen = freeze_json(payload)
    if not isinstance(frozen, Mapping):
        raise TypeError("workload task payload must freeze to object")
    object.__setattr__(result, "_payload_cache", frozen)
    return frozen


def workload_task_result_from_payload(payload: JsonValue) -> WorkloadTaskResult:
    if not isinstance(payload, Mapping):
        raise TypeError("workload result payload must be an object")
    receipt_payloads = payload.get("participant_receipts", ())
    completion_payload = payload.get("completion_receipt")
    if not isinstance(receipt_payloads, (tuple, list)):
        raise TypeError("workload participant receipt payload must be a sequence")
    participant_receipts = []
    for method_payload in receipt_payloads:
        if not isinstance(method_payload, Mapping):
            raise TypeError("workload participant receipt row must be object")
        participant_receipts.append((
            str(method_payload["role"]),
            workload_method_receipt_from_payload(method_payload["receipt"]),
        ))
    participant_receipts = tuple(sorted(participant_receipts, key=lambda row: row[0]))
    completion = None
    if completion_payload is not None:
        if not isinstance(completion_payload, Mapping):
            raise TypeError("workload completion receipt payload must be object")
        artifacts = completion_payload.get("artifacts", ())
        if not isinstance(artifacts, (tuple, list)):
            raise TypeError("workload completion artifacts payload must be sequence")
        completion = WorkloadCompletionReceipt(
            completion_key=str(completion_payload["completion_key"]),
            method_generation=(
                None
                if completion_payload.get("method_generation") is None
                else str(completion_payload["method_generation"])
            ),
            artifacts=tuple(str(value) for value in artifacts),
        )
    diagnostics = payload.get("diagnostics", {})
    exports = payload.get("exports", {})
    if not isinstance(diagnostics, Mapping) or not isinstance(exports, Mapping):
        raise TypeError("workload result diagnostics/exports payload must be objects")
    return WorkloadTaskResult(
        task_id=str(payload["task_id"]),
        family=str(payload["family"]),
        success=bool(payload["success"]),
        utility=float(payload["utility"]),
        steps=int(payload["steps"]),
        duration_s=float(payload["duration_s"]),
        lineage_id=str(payload["lineage_id"]),
        failure_reason=str(payload.get("failure_reason", "")),
        participant_receipts=participant_receipts,
        completion_receipt=completion,
        blocked=bool(payload.get("blocked", False)),
        failure_scope=str(payload["failure_scope"]),
        diagnostics=dict(diagnostics),
        exports=dict(exports),
    )


class WorkloadTaskRunError(ExperimentWorkloadFailure):
    def __init__(self, phase: str, code: str, message: str, *, scope: FailureScope) -> None:
        super().__init__(phase, code, message, scope=scope)


__all__ = [
    "WorkloadCompletionReceipt",
    "StaticExperimentTaskProjection", "TaskDefinitionExperimentTaskProjection",
    "WorkloadGraphResult",
    "WorkloadEvaluation", "WorkloadMethodInvocation", "WorkloadMethodReceipt",
    "WorkloadTaskResult", "WorkloadTaskRunError",
    "workload_method_receipt_payload", "workload_method_receipt_from_payload",
    "workload_task_result_payload", "workload_task_result_from_payload",
]
