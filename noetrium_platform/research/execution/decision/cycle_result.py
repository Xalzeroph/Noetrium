from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationResult

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity


@dataclass(frozen=True, slots=True)
class DecisionCycleResult:
    run_id: str
    decision_cycle_id: str
    context_text: str
    primary_result: object
    operation_results: tuple[OperationResult[JsonValue], ...] = ()
    cycle_identity: DecisionCycleIdentity | None = None
