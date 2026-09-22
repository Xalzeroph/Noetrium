from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.environment.runtime.api import ActionResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.method.api import MethodTaskCompletionReceipt


@dataclass(frozen=True, slots=True)
class CommittedCycleRecovery:
    """Recovery result when Method authority proves task completion already committed."""

    action_result: ActionResult
    completion_receipt: MethodTaskCompletionReceipt
    final_context: ExecutionContext
    operation_results: tuple[OperationResult[JsonValue], ...]


__all__ = ["CommittedCycleRecovery"]
