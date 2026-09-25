from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .contracts import PreparedEffectHandle
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectReceipt, ExecutionContext, canonical_digest


class EffectIntentPhase(StrEnum):
    PREPARED = "prepared"
    RESULT_RECORDED = "result_recorded"
    RECONCILED = "reconciled"
    CONSUMED = "consumed"
    NOT_APPLIED = "not_applied"

    @property
    def terminal(self) -> bool:
        return self in {EffectIntentPhase.CONSUMED, EffectIntentPhase.NOT_APPLIED}


@dataclass(frozen=True, slots=True)
class EffectIntent:
    intent_id: str
    request_id: str
    operation_id: str
    request_digest: str
    provider_component_digest: str
    run_id: str
    trace_id: str
    study_id: str | None
    lifetime_id: str | None
    task_id: str | None
    decision_cycle_id: str | None
    checkpoint_id: str | None = None
    source_generation: str | None = None
    recovery_handle: PreparedEffectHandle | None = None

    @classmethod
    def build(
        cls,
        *,
        request_id: str,
        request_digest: str,
        operation_id: str,
        provider_component: ComponentIdentity,
        context: ExecutionContext,
        source_generation: str | None = None,
        recovery_handle: PreparedEffectHandle | None = None,
        intent_namespace: str = "effect-intent",
    ) -> "EffectIntent":
        if recovery_handle is not None:
            if (
                recovery_handle.request_id != request_id
                or recovery_handle.request_digest != request_digest
            ):
                raise ValueError("prepared effect handle does not match effect request identity")
        provider_digest = canonical_digest(provider_component)
        identity_material = {
            "request_id": request_id,
            "operation_id": operation_id,
            "provider_component_digest": provider_digest,
            "run_id": context.run_id,
            "study_id": context.study_id,
            "lifetime_id": context.lifetime_id,
            "task_id": context.task_id,
            "decision_cycle_id": context.decision_cycle_id,
            "checkpoint_id": context.checkpoint_id,
        }
        return cls(
            intent_id=f"{intent_namespace}:{canonical_digest(identity_material)}",
            request_id=request_id,
            operation_id=operation_id,
            request_digest=request_digest,
            provider_component_digest=provider_digest,
            run_id=context.run_id,
            trace_id=context.trace_id,
            study_id=context.study_id,
            lifetime_id=context.lifetime_id,
            task_id=context.task_id,
            decision_cycle_id=context.decision_cycle_id,
            checkpoint_id=context.checkpoint_id,
            source_generation=source_generation,
            recovery_handle=recovery_handle,
        )


@dataclass(frozen=True, slots=True)
class EffectCompletionEvidence:
    completion_key: str
    completion_operation_id: str
    consumer_component_digest: str
    consumer_generation: str | None = None

    def __post_init__(self) -> None:
        if not self.completion_key.strip():
            raise ValueError("completion_key must be non-empty")
        if not self.completion_operation_id.strip():
            raise ValueError("completion_operation_id must be non-empty")
        if not self.consumer_component_digest.strip():
            raise ValueError("consumer_component_digest must be non-empty")


@dataclass(frozen=True, slots=True)
class EffectIntentRecord:
    intent: EffectIntent
    phase: EffectIntentPhase
    effect: EffectReceipt | None = None
    effect_digest: str | None = None
    consumption: EffectCompletionEvidence | None = None
    consumption_digest: str | None = None


@dataclass(frozen=True, slots=True)
class EffectIntentPrepareResult:
    record: EffectIntentRecord
    created: bool


class EffectIntentConflict(RuntimeError):
    pass


class EffectJournalIntegrityError(ValueError):
    """Persistent effect WAL content disagrees with its identity/index metadata."""


class EffectRecoveryRequired(RuntimeError):
    """A durable external effect cannot safely progress without authoritative reconciliation."""


class EffectAlreadyConsumed(EffectRecoveryRequired):
    """The exact effect intent is already consumed and must not be replayed."""


class PendingEffectRecoveryRequired(EffectRecoveryRequired):
    """A prior non-terminal effect in the same run/lifetime must be reconciled first."""


class EffectRecoveryAnchorMissing(EffectRecoveryRequired):
    """A non-terminal durable effect cannot resume without its verified checkpoint anchor."""


@runtime_checkable
class EffectIntentJournal(Protocol):
    """Write-ahead authority for arbitrary external effects.

    PREPARED means only that execution entered the may-have-happened region.  The
    journal owns no provider capability and cannot infer whether an effect happened.
    """

    durability: str

    def prepare(self, intent: EffectIntent) -> EffectIntentPrepareResult: ...
    def load(self, intent_id: str) -> EffectIntentRecord | None: ...
    def record_result(self, intent_id: str, *, request_digest: str, effect: EffectReceipt | None) -> EffectIntentRecord: ...
    def record_reconciled(self, intent_id: str, *, request_digest: str, effect: EffectReceipt) -> EffectIntentRecord: ...
    def record_consumed(self, intent_id: str, *, request_digest: str, consumption: EffectCompletionEvidence) -> EffectIntentRecord: ...
    def record_not_applied(self, intent_id: str, *, request_digest: str, effect: EffectReceipt) -> EffectIntentRecord: ...
    def unresolved_for_scope(
        self, *, run_id: str, lifetime_id: str | None, exclude_intent_id: str | None = None
    ) -> tuple[EffectIntentRecord, ...]: ...


def effect_digest(effect: EffectReceipt | None) -> str | None:
    return canonical_digest(effect) if effect is not None else None


def consumption_digest(consumption: EffectCompletionEvidence | None) -> str | None:
    return canonical_digest(consumption) if consumption is not None else None


__all__ = [
    "EffectCompletionEvidence",
    "EffectIntent",
    "EffectIntentConflict",
    "EffectIntentJournal",
    "EffectJournalIntegrityError",
    "EffectRecoveryRequired",
    "EffectAlreadyConsumed",
    "PendingEffectRecoveryRequired",
    "EffectRecoveryAnchorMissing",
    "EffectIntentPhase",
    "EffectIntentPrepareResult",
    "EffectIntentRecord",
    "consumption_digest",
    "effect_digest",
]
