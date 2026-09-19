from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math
import re
import time

from noetrium_platform.research.execution.command.api import CommandId

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize_optional_effect_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text or null")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    return normalized


class OperationState(StrEnum):
    CREATED="created"; QUEUED="queued"; ADMITTED="admitted"; RUNNING="running"; CANCELLING="cancelling"
    RECOVERING="recovering"; UNKNOWN_EFFECT="unknown_effect"; COMPLETED="completed"; FAILED="failed"; CANCELLED="cancelled"


class OperationEffectProfile(StrEnum):
    NONE="none"; IDEMPOTENT="idempotent"; RECONCILABLE="reconcilable"; NON_IDEMPOTENT="non_idempotent"


class OperationEffectCertainty(StrEnum):
    NOT_EXECUTED="not_executed"; EXECUTED="executed"; UNKNOWN="unknown"


class OperationFailureKind(StrEnum):
    ADMISSION_REJECTED="admission_rejected"; SCHEDULING_TIMEOUT="scheduling_timeout"
    CAPABILITY_UNAVAILABLE="capability_unavailable"; CAPABILITY_REVOKED="capability_revoked"
    OPERATION_FAILURE="operation_failure"; WORKFLOW_FAILURE="workflow_failure"; CANCELLATION="cancellation"
    EXTERNAL_EFFECT_UNCERTAIN="external_effect_uncertain"; DEPENDENCY_FAILURE="dependency_failure"
    RUNTIME_FAILURE="runtime_failure"; PERSISTENCE_FAILURE="persistence_failure"; RECOVERY_FAILURE="recovery_failure"


@dataclass(frozen=True, slots=True)
class OperationId:
    value: str
    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("operation_id must be text")
        value=self.value.strip()
        if not value: raise ValueError("operation_id required")
        object.__setattr__(self,"value",value)


@dataclass(frozen=True, slots=True)
class EffectId:
    value: str
    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("effect_id must be text")
        value=self.value.strip()
        if not value: raise ValueError("effect_id required")
        object.__setattr__(self,"value",value)


@dataclass(frozen=True, slots=True)
class OperationFailure:
    kind: OperationFailureKind
    code: str
    message: str
    retryable: bool=False
    reconciliation_required: bool=False
    def __post_init__(self) -> None:
        if not isinstance(self.kind, OperationFailureKind):
            raise TypeError("operation failure kind must be OperationFailureKind")
        if not isinstance(self.code, str) or not isinstance(self.message, str):
            raise TypeError("operation failure code/message must be text")
        if not isinstance(self.retryable, bool) or not isinstance(self.reconciliation_required, bool):
            raise TypeError("operation failure retry/reconciliation flags must be bool")
        code = self.code.strip()
        message = self.message.strip()
        if not code or not message:
            raise ValueError("operation failure code/message required")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        if self.kind is OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN and not self.reconciliation_required:
            raise ValueError("uncertain external effect must require reconciliation")


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: OperationId
    command_id: CommandId
    state: OperationState
    version: int
    created_at_unix: float
    updated_at_unix: float
    parent_operation_id: OperationId | None=None
    effect_id: EffectId | None=None
    effect_profile: OperationEffectProfile=OperationEffectProfile.NONE
    effect_certainty: OperationEffectCertainty=OperationEffectCertainty.NOT_EXECUTED
    result_digest: str | None=None
    failure: OperationFailure | None=None
    cancellation_requested: bool=False
    cancellation_reason: str | None=None
    effect_request_id: str | None=None
    effect_request_digest: str | None=None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, OperationId):
            raise TypeError("operation_id must be OperationId")
        if not isinstance(self.command_id, CommandId):
            raise TypeError("command_id must be CommandId")
        if not isinstance(self.state, OperationState):
            raise TypeError("operation state must be OperationState")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("operation version must be integer")
        if self.version < 0:
            raise ValueError("operation version cannot be negative")
        if isinstance(self.created_at_unix, bool) or not isinstance(self.created_at_unix, (int, float)):
            raise TypeError("operation created_at_unix must be numeric")
        if isinstance(self.updated_at_unix, bool) or not isinstance(self.updated_at_unix, (int, float)):
            raise TypeError("operation updated_at_unix must be numeric")
        created_at = float(self.created_at_unix)
        updated_at = float(self.updated_at_unix)
        if not math.isfinite(created_at) or created_at < 0:
            raise ValueError("operation created_at_unix must be finite and non-negative")
        if not math.isfinite(updated_at) or updated_at < created_at:
            raise ValueError("operation updated_at_unix must be finite and not precede creation")
        object.__setattr__(self, "created_at_unix", created_at)
        object.__setattr__(self, "updated_at_unix", updated_at)
        if self.parent_operation_id is not None and not isinstance(self.parent_operation_id, OperationId):
            raise TypeError("parent_operation_id must be OperationId or null")
        if self.parent_operation_id == self.operation_id:
            raise ValueError("operation cannot be its own parent")
        if self.effect_id is not None and not isinstance(self.effect_id, EffectId):
            raise TypeError("effect_id must be EffectId or null")
        request_id = _normalize_optional_effect_text(self.effect_request_id, "effect_request_id")
        request_digest = _normalize_optional_effect_text(self.effect_request_digest, "effect_request_digest")
        object.__setattr__(self, "effect_request_id", request_id)
        object.__setattr__(self, "effect_request_digest", request_digest)
        if not isinstance(self.effect_profile, OperationEffectProfile):
            raise TypeError("effect_profile must be OperationEffectProfile")
        if not isinstance(self.effect_certainty, OperationEffectCertainty):
            raise TypeError("effect_certainty must be OperationEffectCertainty")
        if self.failure is not None and not isinstance(self.failure, OperationFailure):
            raise TypeError("operation failure must be OperationFailure or null")
        if self.result_digest is not None:
            if not isinstance(self.result_digest, str):
                raise TypeError("operation result_digest must be text or null")
            digest = self.result_digest.strip().lower()
            if not _SHA256.fullmatch(digest):
                raise ValueError("operation result_digest must be a SHA-256 hex digest")
            if self.state is not OperationState.COMPLETED:
                raise ValueError("operation result_digest is valid only for COMPLETED state")
            object.__setattr__(self, "result_digest", digest)
        if self.effect_profile is not OperationEffectProfile.NONE:
            if self.effect_id is None or request_id is None or request_digest is None:
                raise ValueError("effectful operation requires stable effect_id/request_id/request_digest before execution")
        elif self.effect_id is not None or request_id is not None or request_digest is not None:
            raise ValueError("effect-free operation cannot carry external effect identity")
        if self.effect_profile is OperationEffectProfile.NONE:
            if self.effect_certainty is not OperationEffectCertainty.NOT_EXECUTED:
                raise ValueError("effect-free operation must remain NOT_EXECUTED")
        if self.state is OperationState.UNKNOWN_EFFECT:
            if self.effect_certainty is not OperationEffectCertainty.UNKNOWN:
                raise ValueError("UNKNOWN_EFFECT requires UNKNOWN effect certainty")
            if self.failure is None or self.failure.kind is not OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN:
                raise ValueError("UNKNOWN_EFFECT requires uncertain-effect failure evidence")
        if self.effect_certainty is OperationEffectCertainty.UNKNOWN and self.state is not OperationState.UNKNOWN_EFFECT:
            raise ValueError("UNKNOWN effect certainty is valid only while reconciliation is required")
        if self.failure is not None and self.state not in {OperationState.FAILED, OperationState.UNKNOWN_EFFECT}:
            raise ValueError("operation failure evidence is valid only for FAILED/UNKNOWN_EFFECT states")
        if self.failure is not None and self.failure.kind is OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN:
            if self.state is not OperationState.UNKNOWN_EFFECT:
                raise ValueError("uncertain-effect failure cannot be stored as terminal FAILED state")
        if self.state is OperationState.COMPLETED and self.failure is not None:
            raise ValueError("completed operation cannot carry failure")
        if self.state is OperationState.FAILED and self.failure is None:
            raise ValueError("failed operation requires failure")
        if not isinstance(self.cancellation_requested, bool):
            raise TypeError("operation cancellation_requested must be bool")
        if self.cancellation_reason is not None and not isinstance(self.cancellation_reason, str):
            raise TypeError("operation cancellation_reason must be text or null")
        reason = None if self.cancellation_reason is None else self.cancellation_reason.strip()
        if self.cancellation_requested and not reason:
            raise ValueError("operation cancellation request requires reason")
        if not self.cancellation_requested and reason is not None:
            raise ValueError("operation cancellation reason requires cancellation_requested")
        if self.state in {OperationState.CANCELLING, OperationState.CANCELLED} and not self.cancellation_requested:
            raise ValueError("cancelling/cancelled operation requires durable cancellation intent")
        if self.cancellation_requested and self.state in {
            OperationState.CREATED, OperationState.QUEUED, OperationState.ADMITTED, OperationState.RUNNING,
        }:
            raise ValueError("pre-cancellation operation state cannot carry durable cancellation intent")
        if (
            self.cancellation_requested
            and self.state is OperationState.RECOVERING
            and self.effect_certainty is OperationEffectCertainty.NOT_EXECUTED
        ):
            raise ValueError("NOT_EXECUTED recovery cancellation must already be terminal CANCELLED")
        object.__setattr__(self, "cancellation_reason", reason)

TERMINAL_OPERATION_STATES=frozenset({OperationState.COMPLETED,OperationState.FAILED,OperationState.CANCELLED})
_ALLOWED={
    OperationState.CREATED:{OperationState.QUEUED,OperationState.ADMITTED,OperationState.CANCELLED,OperationState.FAILED},
    OperationState.QUEUED:{OperationState.ADMITTED,OperationState.CANCELLED,OperationState.FAILED},
    OperationState.ADMITTED:{OperationState.RUNNING,OperationState.CANCELLED,OperationState.FAILED},
    OperationState.RUNNING:{OperationState.CANCELLING,OperationState.COMPLETED,OperationState.FAILED,OperationState.UNKNOWN_EFFECT,OperationState.RECOVERING},
    OperationState.CANCELLING:{OperationState.CANCELLED,OperationState.COMPLETED,OperationState.FAILED,OperationState.UNKNOWN_EFFECT},
    OperationState.UNKNOWN_EFFECT:{OperationState.RECOVERING,OperationState.CANCELLED,OperationState.FAILED},
    OperationState.RECOVERING:{OperationState.RUNNING,OperationState.COMPLETED,OperationState.FAILED,OperationState.CANCELLED,OperationState.UNKNOWN_EFFECT},
}


class IllegalOperationTransition(RuntimeError): pass


def _resolved_update_time(snapshot: OperationSnapshot, now_unix: float | None) -> float:
    if now_unix is None:
        return max(snapshot.updated_at_unix, time.time())
    if isinstance(now_unix, bool) or not isinstance(now_unix, (int, float)):
        raise TypeError("operation transition timestamp must be numeric or null")
    resolved = float(now_unix)
    if not math.isfinite(resolved) or resolved < snapshot.updated_at_unix:
        raise ValueError("operation transition timestamp cannot move backwards")
    return resolved


_TRANSITION_EVIDENCE_FIELDS = frozenset({
    "effect_certainty", "result_digest", "failure", "cancellation_requested", "cancellation_reason",
})


def revise_operation(snapshot: OperationSnapshot, *, now_unix: float | None=None, **changes) -> OperationSnapshot:
    if snapshot.state not in {OperationState.UNKNOWN_EFFECT, OperationState.RECOVERING}:
        raise IllegalOperationTransition(f"operation metadata revision not allowed from state: {snapshot.state.value}")
    if (
        snapshot.state is OperationState.RECOVERING
        and snapshot.effect_certainty is OperationEffectCertainty.NOT_EXECUTED
    ):
        raise IllegalOperationTransition(
            "recovering operation with no executed effect must cancel terminally instead of staying RECOVERING"
        )
    if set(changes) != {"cancellation_requested", "cancellation_reason"}:
        raise TypeError("operation revision may only record cancellation intent")
    if changes["cancellation_requested"] is not True:
        raise ValueError("operation revision cannot clear cancellation intent")
    if snapshot.cancellation_requested:
        if changes["cancellation_reason"] != snapshot.cancellation_reason:
            raise ValueError("operation cancellation reason is immutable after first request")
        return snapshot
    return replace(snapshot, version=snapshot.version + 1,
                   updated_at_unix=_resolved_update_time(snapshot, now_unix), **changes)


def _validate_monotonic_transition_evidence(snapshot: OperationSnapshot, changes: dict[str, object]) -> None:
    if snapshot.cancellation_requested:
        if "cancellation_requested" in changes and changes["cancellation_requested"] is not True:
            raise ValueError("operation transition cannot clear cancellation intent")
        if "cancellation_reason" in changes and changes["cancellation_reason"] != snapshot.cancellation_reason:
            raise ValueError("operation cancellation reason is immutable after first request")
    if snapshot.effect_certainty is OperationEffectCertainty.EXECUTED:
        certainty = changes.get("effect_certainty", OperationEffectCertainty.EXECUTED)
        if certainty is not OperationEffectCertainty.EXECUTED:
            raise ValueError("executed external effect certainty cannot regress")


def transition_operation(snapshot: OperationSnapshot, target: OperationState, *, now_unix: float | None=None, **changes) -> OperationSnapshot:
    if not isinstance(target, OperationState):
        raise TypeError("operation transition target must be OperationState")
    unexpected = set(changes) - _TRANSITION_EVIDENCE_FIELDS
    if unexpected:
        raise TypeError(f"operation transition cannot mutate authority fields: {sorted(unexpected)}")
    if target not in _ALLOWED.get(snapshot.state, set()):
        raise IllegalOperationTransition(f"illegal operation transition: {snapshot.state.value} -> {target.value}")
    if (
        target is OperationState.FAILED
        and snapshot.effect_profile is not OperationEffectProfile.NONE
        and snapshot.state in {OperationState.RUNNING, OperationState.CANCELLING}
    ):
        raise IllegalOperationTransition(
            "effectful in-flight failure requires UNKNOWN_EFFECT reconciliation before terminal failure"
        )
    _validate_monotonic_transition_evidence(snapshot, changes)
    return replace(snapshot, state=target, version=snapshot.version + 1,
                   updated_at_unix=_resolved_update_time(snapshot, now_unix), **changes)

__all__=["EffectId","IllegalOperationTransition","OperationEffectCertainty","OperationEffectProfile","OperationFailure",
         "OperationFailureKind","OperationId","OperationSnapshot","OperationState","TERMINAL_OPERATION_STATES",
         "revise_operation","transition_operation"]
