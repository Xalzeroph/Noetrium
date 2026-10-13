from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.failure.api import failure_field


@dataclass(frozen=True, slots=True)
class TriageReport:
    headline: str
    exact_location: str
    scientific_risk: str
    next_action: str
    query_keys: tuple[str, ...]


def triage(failure: NoetriumUnit) -> TriageReport:
    ctx = failure_field(failure, "context")
    exact = "/".join(x for x in [failure_field(failure, "component_id"), failure_field(failure, "stage"), ctx.task_id, ctx.decision_cycle_id, failure_field(failure, "operation_id")] if x)
    action = (
        failure_field(failure, "recommended_recovery").value
        if failure_field(failure, "recommended_recovery") is not None
        else "manual_diagnosis"
    )
    return TriageReport(
        headline=f"{failure_field(failure, "failure_domain")}:{failure_field(failure, "failure_code")}",
        exact_location=exact,
        scientific_risk=failure_field(failure, "scientific_validity_risk").value,
        next_action=action,
        query_keys=tuple(x for x in [failure_field(failure, "failure_id"), ctx.run_id, ctx.trace_id, ctx.span_id, ctx.task_id, ctx.decision_cycle_id] if x),
    )
