"""Effect journal authority over universal NoetriumUnit records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import EffectReceipt
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .effect_units import EffectIntentPhase


@dataclass(frozen=True, slots=True)
class EffectIntentPrepareResult:
    """Ephemeral authority receipt; durable truth is the record Unit."""

    record: NoetriumUnit
    created: bool


class EffectIntentConflict(RuntimeError):
    pass


class EffectJournalIntegrityError(ValueError):
    """Persistent effect WAL content disagrees with identity/index metadata."""


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
    """Write-ahead Authority for external effects.

    Every durable intent/record/completion/snapshot is a NoetriumUnit. The
    journal owns ordering/CAS/durability, never provider truth.
    """

    durability: str

    def prepare(self, intent: NoetriumUnit) -> EffectIntentPrepareResult: ...
    def prepare_scoped(self, intent: NoetriumUnit) -> EffectIntentPrepareResult: ...
    def load(self, intent_id: str) -> NoetriumUnit | None: ...
    def record_result(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt | None,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...
    def record_terminal_result(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
        result_snapshot: NoetriumUnit | None = None,
        consumption: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...

    def record_reconciled(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...
    def record_consumed(
        self,
        intent_id: str,
        *,
        request_digest: str,
        consumption: NoetriumUnit,
    ) -> NoetriumUnit: ...
    def record_not_applied(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
    ) -> NoetriumUnit: ...
    def record_indeterminate(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
    ) -> NoetriumUnit: ...
    def unresolved_for_scope(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        exclude_intent_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]: ...
    def records_for_run(self, run_id: str) -> tuple[NoetriumUnit, ...]: ...
    def close(self) -> None: ...


__all__ = [
    "EffectAlreadyConsumed",
    "EffectIntentConflict",
    "EffectIntentJournal",
    "EffectIntentPhase",
    "EffectIntentPrepareResult",
    "EffectJournalIntegrityError",
    "EffectRecoveryAnchorMissing",
    "EffectRecoveryRequired",
    "PendingEffectRecoveryRequired",
]
