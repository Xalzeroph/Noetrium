from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectReceipt
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.capabilities.api import (
    EffectIntentJournal,
    PendingEffectRecoveryRequired,
    intent_field,
    record_field,
)


EFFECT_JOURNAL_IDENTITY = ComponentIdentity(
    "platform.effect_intent_journal",
    "effect_intent_journal",
    "1",
    "1",
    "effect-journal-unit-v3",
)


def _intent_text(intent: NoetriumUnit, name: str) -> str:
    return str(intent_field(intent, name))


class EffectIntentOperations:
    """Thin workflow surface over the Effect Journal durable Authority.

    The journal already owns CAS, causal event history and crash durability.
    Wrapping every journal read/write in a second durable Operation created a
    duplicate persistence authority and multiplied FULL-sync writes on every
    external effect. Provider execution remains an Operation; journal state is
    persisted exactly once by the journal itself.
    """

    def __init__(self, journal: EffectIntentJournal) -> None:
        self._effect_journal = journal

    @property
    def durability(self) -> str:
        return self._effect_journal.durability

    @property
    def component_identity(self) -> ComponentIdentity:
        return EFFECT_JOURNAL_IDENTITY

    def close(self) -> None:
        self._effect_journal.close()

    def inspect(self, intent: NoetriumUnit) -> NoetriumUnit | None:
        return self._effect_journal.load(_intent_text(intent, "intent_id"))

    def require_scope_clear(self, intent: NoetriumUnit) -> None:
        intent_id = _intent_text(intent, "intent_id")
        pending = self._effect_journal.unresolved_for_scope(
            run_id=_intent_text(intent, "run_id"),
            lifetime_id=intent_field(intent, "lifetime_id"),
            exclude_intent_id=intent_id,
        )
        if pending:
            summary = ",".join(
                f"{intent_field(record_field(row, 'intent'), 'intent_id')}:"
                f"{record_field(row, 'phase').value}"
                for row in pending[:8]
            )
            raise PendingEffectRecoveryRequired(
                f"run/lifetime has {len(pending)} unresolved external "
                f"effect intent(s): {summary}"
            )

    def prepare(self, intent: NoetriumUnit):
        return self._effect_journal.prepare_scoped(intent)

    def record_result(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt | None,
        *,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        return self._effect_journal.record_result(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            effect=effect,
            result_snapshot=result_snapshot,
        )

    def record_terminal_result(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
        *,
        result_snapshot: NoetriumUnit | None = None,
        consumption: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        return self._effect_journal.record_terminal_result(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            effect=effect,
            result_snapshot=result_snapshot,
            consumption=consumption,
        )

    def record_reconciled(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
        *,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        return self._effect_journal.record_reconciled(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            effect=effect,
            result_snapshot=result_snapshot,
        )

    def record_consumed(
        self,
        intent: NoetriumUnit,
        consumption: NoetriumUnit,
    ) -> NoetriumUnit:
        return self._effect_journal.record_consumed(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            consumption=consumption,
        )

    def record_not_applied(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
    ) -> NoetriumUnit:
        return self._effect_journal.record_not_applied(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            effect=effect,
        )

    def record_indeterminate(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
    ) -> NoetriumUnit:
        return self._effect_journal.record_indeterminate(
            _intent_text(intent, "intent_id"),
            request_digest=_intent_text(intent, "request_digest"),
            effect=effect,
        )


__all__ = ["EFFECT_JOURNAL_IDENTITY", "EffectIntentOperations"]
