from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math

from noetrium_platform.research.experimentation.experiment.api import ExperimentWorkloadFailure, FailureScope
from noetrium_platform.research.execution.workflow.api import MethodProgram, MethodRuntimeContext
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, freeze_json


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
    def __post_init__(self) -> None:
        if any(type(v) is not str or not v.strip() for v in (self.run_id, self.status, self.evidence_status)):
            raise ValueError("workload method receipt identity/status fields are required")
        for name in ("program_digest", "run_digest"):
            value = getattr(self, name)
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise ValueError(f"workload method receipt {name} must be SHA-256 hex")
        if type(self.step_count) is not int or isinstance(self.step_count, bool) or self.step_count < 0:
            raise ValueError("workload method receipt step_count must be non-negative integer")


def _freeze_mapping(value: Mapping[str, JsonValue], *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    frozen = freeze_json(dict(value))
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
    method_receipt: WorkloadMethodReceipt | None = None
    completion_receipt: WorkloadCompletionReceipt | None = None
    blocked: bool = False
    failure_scope: str = FailureScope.TASK.value
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)
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
        if self.method_receipt is not None and not isinstance(self.method_receipt, WorkloadMethodReceipt):
            raise TypeError("workload method_receipt must be WorkloadMethodReceipt")
        if self.completion_receipt is not None and not isinstance(self.completion_receipt, WorkloadCompletionReceipt):
            raise TypeError("workload completion_receipt must be WorkloadCompletionReceipt")
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, field_name="workload diagnostics"))


class WorkloadTaskRunError(ExperimentWorkloadFailure):
    def __init__(self, phase: str, code: str, message: str, *, scope: FailureScope) -> None:
        super().__init__(phase, code, message, scope=scope)


__all__ = [
    "WorkloadCompletionReceipt",
    "WorkloadEvaluation", "WorkloadMethodInvocation", "WorkloadMethodReceipt",
    "WorkloadTaskResult", "WorkloadTaskRunError",
]
