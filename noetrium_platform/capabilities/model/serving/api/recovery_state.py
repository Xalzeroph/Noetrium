from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .recovery import RecoveryPlan, RecoveryStep


class DurableRecoveryPhase(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


@dataclass(frozen=True, slots=True)
class DurableRecoveryAttempt:
    attempt_id: str
    source_run_id: str
    plan_digest: str
    phase: DurableRecoveryPhase
    completed_steps: tuple[str, ...]
    current_step: str | None
    current_step_status: str | None
    current_effect_certainty: str | None
    evidence_refs: tuple[str, ...]
    updated_at: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.updated_at, bool)
            or not isinstance(self.updated_at, (int, float))
            or not math.isfinite(float(self.updated_at))
            or self.updated_at < 0
        ):
            raise ValueError("durable recovery updated_at must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RecoveryResumeDecision:
    steps: tuple[RecoveryStep, ...]
    completed_prefix: tuple[str, ...]
    reason: str


def recovery_plan_digest(plan: RecoveryPlan) -> str:
    payload = {
        "source_run_id": plan.source_run_id,
        "model": plan.frozen_identity.resume_key(),
        "deployment_digest": plan.frozen_deployment_digest,
        "steps": [step.value for step in plan.steps],
    }
    return canonical_digest(payload)


def new_recovery_attempt(attempt_id: str, plan: RecoveryPlan, *, now: float) -> DurableRecoveryAttempt:
    return DurableRecoveryAttempt(
        attempt_id=attempt_id,
        source_run_id=plan.source_run_id,
        plan_digest=recovery_plan_digest(plan),
        phase=DurableRecoveryPhase.PLANNED,
        completed_steps=(),
        current_step=None,
        current_step_status=None,
        current_effect_certainty=None,
        evidence_refs=(),
        updated_at=now,
    )


def begin_recovery_step(
    attempt: DurableRecoveryAttempt,
    step: RecoveryStep,
    *,
    now: float,
) -> DurableRecoveryAttempt:
    certainty = (
        "unknown"
        if step in {RecoveryStep.RESTART_EXACT_MODEL, RecoveryStep.RESUME_RUN_EXACT}
        else "no_effect"
    )
    return replace(
        attempt,
        phase=DurableRecoveryPhase.RUNNING,
        current_step=step.value,
        current_step_status="running",
        current_effect_certainty=certainty,
        updated_at=now,
    )


def complete_recovery_step(
    attempt: DurableRecoveryAttempt,
    step: RecoveryStep,
    evidence: tuple[str, ...],
    *,
    now: float,
) -> DurableRecoveryAttempt:
    certainty = (
        "confirmed"
        if step in {RecoveryStep.RESTART_EXACT_MODEL, RecoveryStep.RESUME_RUN_EXACT}
        else "no_effect"
    )
    return replace(
        attempt,
        completed_steps=attempt.completed_steps + (step.value,),
        current_step=step.value,
        current_step_status="completed",
        current_effect_certainty=certainty,
        evidence_refs=attempt.evidence_refs + evidence,
        updated_at=now,
    )


def fail_recovery_step(
    attempt: DurableRecoveryAttempt,
    step: RecoveryStep,
    *,
    now: float,
) -> DurableRecoveryAttempt:
    certainty = (
        "unknown"
        if step in {RecoveryStep.RESTART_EXACT_MODEL, RecoveryStep.RESUME_RUN_EXACT}
        else "no_effect"
    )
    return replace(
        attempt,
        phase=DurableRecoveryPhase.FAILED,
        current_step=step.value,
        current_step_status="failed",
        current_effect_certainty=certainty,
        updated_at=now,
    )


def succeed_recovery(attempt: DurableRecoveryAttempt, *, now: float) -> DurableRecoveryAttempt:
    return replace(
        attempt,
        phase=DurableRecoveryPhase.SUCCEEDED,
        current_step=None,
        current_step_status=None,
        current_effect_certainty=None,
        updated_at=now,
    )


def decide_resume(attempt: DurableRecoveryAttempt, plan: RecoveryPlan) -> RecoveryResumeDecision:
    if attempt.plan_digest != recovery_plan_digest(plan):
        raise ValueError("recovery attempt/plan identity drift")
    if attempt.phase == DurableRecoveryPhase.SUCCEEDED:
        return RecoveryResumeDecision((), tuple(step.value for step in plan.steps), "already_succeeded")

    all_steps = plan.steps
    if attempt.current_step and attempt.current_step_status in {"running", "failed"}:
        current = RecoveryStep(attempt.current_step)
        if current == RecoveryStep.RESTART_EXACT_MODEL:
            index = all_steps.index(RecoveryStep.RECONCILE_PROCESS)
            return RecoveryResumeDecision(
                all_steps[index:],
                tuple(step.value for step in all_steps[:index]),
                "model restart effect uncertain; reconcile before any retry",
            )
        if current == RecoveryStep.RESUME_RUN_EXACT:
            index = all_steps.index(RecoveryStep.RECONCILE_RUN)
            return RecoveryResumeDecision(
                all_steps[index:],
                tuple(step.value for step in all_steps[:index]),
                "study resume effect uncertain; reconcile before any retry",
            )
        index = all_steps.index(current)
        return RecoveryResumeDecision(
            all_steps[index:],
            tuple(step.value for step in all_steps[:index]),
            "retry interrupted read-only/idempotent verification step",
        )

    done = len(attempt.completed_steps)
    expected = tuple(step.value for step in all_steps[:done])
    if attempt.completed_steps != expected:
        raise ValueError("durable recovery completed steps are not an exact plan prefix")
    return RecoveryResumeDecision(all_steps[done:], expected, "continue_after_completed_prefix")


__all__ = [
    "DurableRecoveryAttempt",
    "DurableRecoveryPhase",
    "RecoveryResumeDecision",
    "begin_recovery_step",
    "complete_recovery_step",
    "decide_resume",
    "fail_recovery_step",
    "new_recovery_attempt",
    "recovery_plan_digest",
    "succeed_recovery",
]
