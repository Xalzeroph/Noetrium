from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult


@dataclass(frozen=True, slots=True)
class TrialCycleExecution:
    context_text: str
    primary_result: object
    final_context: ExecutionContext
    operation_results: tuple[OperationResult[JsonValue], ...]


__all__ = ["TrialCycleExecution"]
