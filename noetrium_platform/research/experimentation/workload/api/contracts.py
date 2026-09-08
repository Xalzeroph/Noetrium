from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
import math
from types import MappingProxyType

from noetrium_platform.research.experimentation.experiment.api import ExperimentWorkloadFailure, FailureScope
from noetrium_platform.foundation.kernel.kernel import JsonValue


class WorkloadBatchCloseError(RuntimeError):
    """A workload batch failed and its binding could not close cleanly."""

    def __init__(self, primary: BaseException, cleanup: BaseException) -> None:
        super().__init__("workload batch failed and binding close failed")
        self.primary = primary
        self.cleanup = cleanup


@dataclass(frozen=True, slots=True)
class WorkloadCompletionReceipt:
    """Frozen workload-owned completion provenance safe for checkpoint round trips."""

    completion_key: str
    method_generation: str | None = None
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.completion_key) is not str or not self.completion_key.strip():
            raise ValueError("workload completion_key must be a non-empty string")
        if self.method_generation is not None and (
            type(self.method_generation) is not str or not self.method_generation.strip()
        ):
            raise ValueError("workload method_generation must be a non-empty string or None")
        if type(self.artifacts) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.artifacts
        ):
            raise ValueError("workload completion artifacts must be a tuple of non-empty strings")
        if len(self.artifacts) != len(set(self.artifacts)):
            raise ValueError("workload completion artifacts must be unique")


def _normalize_completion_receipt(value: object) -> WorkloadCompletionReceipt | None:
    if value is None:
        return None
    if type(value) is WorkloadCompletionReceipt:
        return value
    try:
        completion_key = value.completion_key
        method_generation = value.method_generation
        artifacts = value.artifacts
    except AttributeError as exc:
        raise TypeError("workload completion_receipt must expose completion provenance") from exc
    return WorkloadCompletionReceipt(completion_key, method_generation, artifacts)


def _freeze_json_value(value: object, *, path: str) -> JsonValue:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value, path=path)
    if type(value) in (list, tuple):
        return _freeze_json_sequence(value, path=path)
    raise TypeError(f"{path} contains unsupported {type(value).__name__}")


def _freeze_json_mapping(value: object, *, path: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must be a mapping")
    frozen: dict[str, JsonValue] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise TypeError(f"{path} contains a non-string key")
        frozen[key] = _freeze_json_value(item, path=f"{path}.{key}")
    return MappingProxyType(frozen)


def _freeze_json_sequence(value: object, *, path: str) -> tuple[JsonValue, ...]:
    if type(value) not in (list, tuple):
        raise TypeError(f"{path} must be a list or tuple")
    return tuple(
        _freeze_json_value(item, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    )


@dataclass(frozen=True, slots=True)
class WorkloadDecision:
    """One environment-neutral planner decision.

    The action vocabulary and payload schema belong to the environment adapter;
    the workload system only transports them and records their identity.
    """

    action_type: str
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    rationale: str = ""
    completion_claim: bool = False

    def __post_init__(self) -> None:
        if type(self.action_type) is not str or not self.action_type.strip():
            raise ValueError("workload decision action_type must be a non-empty string")
        if type(self.rationale) is not str:
            raise TypeError("workload decision rationale must be a string")
        if type(self.completion_claim) is not bool:
            raise TypeError("workload decision completion_claim must be boolean")
        object.__setattr__(
            self, "payload", _freeze_json_mapping(self.payload, path="workload decision payload")
        )


def _require_result_string(value: object, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"workload task result {field_name} must be a string")


def _require_result_number(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"workload task result {field_name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"workload task result {field_name} must be finite")


def _validate_result_collections(
    planner_actions: tuple[Mapping[str, JsonValue], ...],
    decision_cycles: tuple[Mapping[str, JsonValue], ...],
    diagnostics: Mapping[str, JsonValue],
) -> None:
    if type(planner_actions) is not tuple or any(
        not isinstance(item, Mapping) for item in planner_actions
    ):
        raise TypeError("workload planner_actions must be a tuple of mappings")
    if type(decision_cycles) is not tuple or any(
        not isinstance(item, Mapping) for item in decision_cycles
    ):
        raise TypeError("workload decision_cycles must be a tuple of mappings")
    if not isinstance(diagnostics, Mapping):
        raise TypeError("workload diagnostics must be a mapping")


def _freeze_result_collections(result: "WorkloadTaskResult") -> None:
    object.__setattr__(result, "planner_actions", tuple(
        _freeze_json_mapping(item, path=f"workload planner_actions[{index}]")
        for index, item in enumerate(result.planner_actions)
    ))
    object.__setattr__(result, "decision_cycles", tuple(
        _freeze_json_mapping(item, path=f"workload decision_cycles[{index}]")
        for index, item in enumerate(result.decision_cycles)
    ))
    object.__setattr__(
        result, "diagnostics", _freeze_json_mapping(result.diagnostics, path="workload diagnostics")
    )


def _validate_workload_task_result(result: "WorkloadTaskResult") -> None:
    _require_result_string(result.task_id, "task_id")
    _require_result_string(result.family, "family")
    _require_result_string(result.lineage_id, "lineage_id")
    _require_result_string(result.failure_reason, "failure_reason")
    _require_result_string(result.failure_scope, "failure_scope")
    if not result.task_id.strip() or not result.family.strip() or not result.lineage_id.strip():
        raise ValueError("workload task result identity fields must be non-empty")
    if type(result.success) is not bool or type(result.blocked) is not bool:
        raise TypeError("workload task result success/blocked must be booleans")
    if type(result.steps) is not int or type(result.memory_queries) is not int:
        raise TypeError("workload task result counts must be integers")
    if result.steps < 0 or result.memory_queries < 0:
        raise ValueError("workload task result counts cannot be negative")
    _require_result_number(result.utility, "utility")
    _require_result_number(result.duration_s, "duration_s")
    if result.duration_s < 0:
        raise ValueError("workload task result duration_s cannot be negative")
    if not result.failure_scope.strip():
        raise ValueError("workload task result failure_scope must be non-empty")
    try:
        FailureScope(result.failure_scope)
    except ValueError as exc:
        raise ValueError("workload task result failure_scope is not declared") from exc
    if result.success:
        if result.blocked:
            raise ValueError("workload task result cannot be both successful and blocked")
        if result.failure_reason:
            raise ValueError("successful workload task result cannot carry a failure reason")
    elif not result.failure_reason.strip():
        raise ValueError("failed or blocked workload task result requires a failure reason")
    _validate_result_collections(result.planner_actions, result.decision_cycles, result.diagnostics)


@dataclass(frozen=True, slots=True)
class WorkloadTaskResult:
    """Generic task receipt shared by MC and non-MC workload adapters."""

    task_id: str
    family: str
    success: bool
    utility: float
    steps: int
    duration_s: float
    lineage_id: str
    failure_reason: str = ""
    memory_queries: int = 0
    planner_actions: tuple[Mapping[str, JsonValue], ...] = ()
    decision_cycles: tuple[Mapping[str, JsonValue], ...] = ()
    completion_receipt: WorkloadCompletionReceipt | None = None
    blocked: bool = False
    failure_scope: str = FailureScope.TASK.value
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_workload_task_result(self)
        object.__setattr__(
            self, "completion_receipt", _normalize_completion_receipt(self.completion_receipt)
        )
        _freeze_result_collections(self)



@dataclass(frozen=True, slots=True)
class WorkloadBatchResult:
    """Environment-neutral receipt for one ordered task batch."""

    task_results: tuple[WorkloadTaskResult, ...]

    def __post_init__(self) -> None:
        if type(self.task_results) is not tuple:
            raise ValueError("workload batch task_results must be an immutable tuple")
        if any(type(result) is not WorkloadTaskResult for result in self.task_results):
            raise ValueError("workload batch task_results must contain WorkloadTaskResult values")
        task_ids = tuple(result.task_id for result in self.task_results)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("workload batch task ids must be unique")

    @property
    def success_rate(self) -> float:
        return sum(result.success for result in self.task_results) / max(1, len(self.task_results))

    @property
    def utility_mean(self) -> float:
        return sum(result.utility for result in self.task_results) / max(1, len(self.task_results))

    @property
    def total_steps(self) -> int:
        return sum(result.steps for result in self.task_results)

    @property
    def total_duration_s(self) -> float:
        return sum(result.duration_s for result in self.task_results)

    @property
    def memory_queries(self) -> int:
        return sum(result.memory_queries for result in self.task_results)

    @property
    def blocked_count(self) -> int:
        return sum(result.blocked for result in self.task_results)

    @property
    def failed_count(self) -> int:
        return sum(not result.success and not result.blocked for result in self.task_results)


class WorkloadTaskRunError(ExperimentWorkloadFailure):
    """Failure raised by the generic runner with explicit continuation scope."""

    def __init__(
        self,
        phase: str,
        code: str,
        message: str,
        *,
        scope: FailureScope,
    ) -> None:
        super().__init__(phase, code, message, scope=scope)


__all__ = [
    "WorkloadBatchCloseError",
    "WorkloadBatchResult",
    "WorkloadCompletionReceipt",
    "WorkloadDecision",
    "WorkloadTaskResult",
    "WorkloadTaskRunError",
]
