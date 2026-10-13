from __future__ import annotations

from dataclasses import replace

from noetrium_platform.foundation.kernel.kernel.errors import SafeExceptionDescriptor

from .contracts import RuntimeStep
from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase


def rewind_for_resume(
    state: RuntimeControlState,
    *,
    completed_prefix: tuple[str, ...],
    now: float,
) -> RuntimeControlState:
    return replace(
        state,
        completed_actions=completed_prefix,
        current_action=None,
        current_mutating=False,
        phase=RuntimeTxnPhase.PLANNED,
        updated_at=now,
    )


def begin_runtime_action(state: RuntimeControlState, step: RuntimeStep, *, now: float) -> RuntimeControlState:
    return replace(
        state,
        phase=RuntimeTxnPhase.RUNNING,
        current_action=step.action.value,
        current_mutating=step.mutating,
        last_error_type=None,
        last_error=None,
        last_error_digest=None,
        updated_at=now,
    )


def fail_runtime_action(
    state: RuntimeControlState,
    *,
    recovery_required: bool,
    error: SafeExceptionDescriptor,
    now: float,
) -> RuntimeControlState:
    return replace(
        state,
        phase=RuntimeTxnPhase.RECOVERY_REQUIRED if recovery_required else RuntimeTxnPhase.FAILED,
        last_error_type=error.error_type,
        last_error=error.safe_message,
        last_error_digest=error.error_digest,
        updated_at=now,
    )


def complete_runtime_action(
    state: RuntimeControlState,
    step: RuntimeStep,
    evidence_refs: tuple[str, ...],
    *,
    now: float,
) -> RuntimeControlState:
    return replace(
        state,
        completed_actions=state.completed_actions + (step.action.value,),
        evidence_refs=state.evidence_refs + evidence_refs,
        current_action=None,
        current_mutating=False,
        phase=RuntimeTxnPhase.RUNNING,
        updated_at=now,
    )


def succeed_runtime(state: RuntimeControlState, *, now: float) -> RuntimeControlState:
    return replace(
        state,
        phase=RuntimeTxnPhase.SUCCEEDED,
        current_action=None,
        current_mutating=False,
        updated_at=now,
    )


__all__ = [
    "begin_runtime_action",
    "complete_runtime_action",
    "fail_runtime_action",
    "rewind_for_resume",
    "succeed_runtime",
]
