from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.runtime.api import ActionResult, Observation
from .action_contracts import ActionPreflightProof
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.method.api import MethodTaskCompletionReceipt, RecallResult


@dataclass(frozen=True, slots=True)
class StudyTaskCompletionExecution:
    receipt: MethodTaskCompletionReceipt | None
    operation_results: tuple[OperationResult[JsonValue], ...]


@runtime_checkable
class ContextActionOperationPort(Protocol):
    def preflight_action(self, action_type: str, action_payload: JsonValue, context: ExecutionContext) -> tuple[ActionPreflightProof, tuple[OperationResult[JsonValue], ...]]: ...
    def try_recover_committed_cycle(self, action_type: str, action_payload: JsonValue, context: ExecutionContext, preflight: ActionPreflightProof) -> JsonValue | None: ...
    def observe(self, context: ExecutionContext) -> tuple[Observation, OperationResult[JsonValue]]: ...
    def ingest(self, observation: Observation, context: ExecutionContext) -> OperationResult[JsonValue]: ...
    def recall(self, task_text: str, context: ExecutionContext) -> tuple[RecallResult, OperationResult[JsonValue]]: ...
    def act(self, action_type: str, action_payload: JsonValue, context: ExecutionContext, preflight: ActionPreflightProof) -> tuple[ActionResult, tuple[OperationResult[JsonValue], ...]]: ...
    def task_completed(self, action_result: ActionResult, context: ExecutionContext, *, action_type: str, action_payload: JsonValue, preflight: ActionPreflightProof) -> StudyTaskCompletionExecution: ...


__all__ = ["ContextActionOperationPort", "StudyTaskCompletionExecution"]
