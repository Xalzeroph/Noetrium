from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import (
    FrozenRuntimeIdentityViolation,
    RuntimeOperationalHealthUnavailable,
)

from .contracts import RuntimeStep


@dataclass(frozen=True, slots=True)
class RuntimeFailureDecision:
    recovery_required: bool
    classification: str


def classify_runtime_failure(step: RuntimeStep, cause: BaseException) -> RuntimeFailureDecision:
    """Classify recovery from generic platform semantics, never concrete Service/Model types."""

    if isinstance(cause, FrozenRuntimeIdentityViolation):
        return RuntimeFailureDecision(False, "frozen_identity_violation")
    if isinstance(cause, RuntimeOperationalHealthUnavailable):
        return RuntimeFailureDecision(
            step.mutating or step.failure_reconcile_anchor is not None,
            "operational_health_unavailable",
        )
    return RuntimeFailureDecision(
        step.mutating or step.failure_reconcile_anchor is not None,
        "step_default",
    )


__all__ = ["RuntimeFailureDecision", "classify_runtime_failure"]
