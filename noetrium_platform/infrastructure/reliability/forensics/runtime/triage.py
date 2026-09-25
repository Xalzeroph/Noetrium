from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope


@dataclass(frozen=True, slots=True)
class TriageReport:
    headline: str
    exact_location: str
    scientific_risk: str
    next_action: str
    query_keys: tuple[str, ...]


def triage(failure: FailureEnvelope) -> TriageReport:
    ctx = failure.context
    exact = "/".join(x for x in [failure.component_id, failure.stage, ctx.task_id, ctx.decision_cycle_id, failure.operation_id] if x)
    action = failure.recommended_recovery.value if failure.recommended_recovery else "manual_diagnosis"
    return TriageReport(
        headline=f"{failure.failure_domain}:{failure.failure_code}",
        exact_location=exact,
        scientific_risk=failure.scientific_validity_risk.value,
        next_action=action,
        query_keys=tuple(x for x in [failure.failure_id, ctx.run_id, ctx.trace_id, ctx.span_id, ctx.task_id, ctx.decision_cycle_id] if x),
    )
