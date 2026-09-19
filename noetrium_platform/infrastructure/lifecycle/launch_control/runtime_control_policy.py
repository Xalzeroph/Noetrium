from __future__ import annotations

from dataclasses import dataclass

from .contracts import RuntimeAction, RuntimePlan, RuntimeStep
from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase


@dataclass(frozen=True, slots=True)
class RuntimeResumeDecision:
    steps: tuple[RuntimeStep, ...]
    reason: str


def resume_decision(state: RuntimeControlState, plan: RuntimePlan) -> RuntimeResumeDecision:
    steps = plan.steps
    actions = tuple(step.action.value for step in steps)
    if state.phase == RuntimeTxnPhase.SUCCEEDED:
        return RuntimeResumeDecision(
            plan.steps,
            "prior_plan_succeeded; revalidate and reconcile exact runtime",
        )
    if state.current_action and state.phase in {
        RuntimeTxnPhase.RUNNING,
        RuntimeTxnPhase.RECOVERY_REQUIRED,
        RuntimeTxnPhase.FAILED,
    }:
        current = RuntimeAction(state.current_action)
        spec = next(step for step in steps if step.action == current)
        if spec.mutating:
            anchor = spec.reconcile_anchor or current
            reason = "mutating effect uncertain; reconcile first"
        elif state.phase is RuntimeTxnPhase.RECOVERY_REQUIRED and spec.failure_reconcile_anchor is not None:
            anchor = spec.failure_reconcile_anchor
            reason = "runtime health verification failed; reconcile exact runtime before revalidation"
        else:
            anchor = current
            reason = "retry non-mutating verification"
        index = next(i for i, step in enumerate(steps) if step.action == anchor)
        return RuntimeResumeDecision(steps[index:], reason)
    done = len(state.completed_actions)
    if state.completed_actions != actions[:done]:
        raise ValueError("completed runtime actions are not an exact plan prefix")
    return RuntimeResumeDecision(steps[done:], "continue exact plan")


__all__ = ["RuntimeResumeDecision", "resume_decision"]
