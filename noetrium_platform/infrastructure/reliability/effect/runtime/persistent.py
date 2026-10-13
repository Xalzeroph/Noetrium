from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectReceipt
from noetrium_platform.foundation.kernel.event import causal_topological_order
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentConflict,
    EffectIntentJournal,
    EffectIntentPhase,
    EffectIntentPrepareResult,
    PendingEffectRecoveryRequired,
    consumed_transition,
    effect_transition,
    effect_record_from_event,
    effect_record_event,
    indeterminate_transition,
    intent_field,
    not_applied_transition,
    prepare_transition,
    require_terminal_result_match,
    record_field,
)
from .generic_codec import EffectJournalDocumentCodec
from .persistence import EffectJournalPersistenceBackend, EncodedEffectIntentRecord


class EffectJournalCodec(Protocol):
    def encode_record(self, record: NoetriumUnit) -> EncodedEffectIntentRecord: ...
    def encode_transition(
        self,
        record: NoetriumUnit,
        *,
        prior: EncodedEffectIntentRecord,
    ) -> EncodedEffectIntentRecord: ...
    def decode_record(self, encoded: EncodedEffectIntentRecord) -> NoetriumUnit: ...
    def completion_digest(self, consumption: NoetriumUnit | None) -> str | None: ...


class EffectIntentJournalRuntime(EffectIntentJournal):
    """Persistent CAS Authority over immutable effect.record Units."""

    def __init__(
        self,
        backend: EffectJournalPersistenceBackend,
        *,
        codec: EffectJournalCodec | None = None,
    ) -> None:
        self.backend = backend
        self.codec: EffectJournalCodec = codec or EffectJournalDocumentCodec()
        self.durability = backend.durability

    def close(self) -> None:
        self.backend.close()

    def load(self, intent_id: str) -> NoetriumUnit | None:
        row = self.backend.read(intent_id)
        if row is None:
            return None
        record = self.codec.decode_record(row)
        event = self.backend.read_event_head(intent_id)
        if event is None or effect_record_from_event(event) != record:
            raise RuntimeError(
                "effect latest-state projection diverged from causal Event Journal: "
                + intent_id
            )
        return record

    @staticmethod
    def _unknown(intent_id: str) -> EffectIntentConflict:
        return EffectIntentConflict(f"unknown effect intent: {intent_id}")

    def prepare(self, intent: NoetriumUnit) -> EffectIntentPrepareResult:
        intent_id = str(intent_field(intent, "intent_id"))
        with self.backend.write_session() as tx:
            current_encoded = tx.read(intent_id)
            current = (
                self.codec.decode_record(current_encoded)
                if current_encoded is not None
                else None
            )
            current_event = (
                tx.read_event_head(intent_id)
                if current_encoded is not None
                else None
            )
            if current is not None and (
                current_event is None
                or effect_record_from_event(current_event) != current
            ):
                raise RuntimeError(
                    "effect projection diverged from causal Event Journal: "
                    + intent_id
                )
            result = prepare_transition(current, intent)
            if result.created:
                event = effect_record_event(result.record)
                if not tx.insert(
                    self.codec.encode_record(result.record),
                    event=event,
                ):
                    raise EffectIntentConflict(
                        f"effect intent concurrent insert conflict: {intent_id}"
                    )
            tx.commit()
            return result

    def prepare_scoped(self, intent: NoetriumUnit) -> EffectIntentPrepareResult:
        """Atomically prove scope-clear and persist PREPARED.

        This is the only safe hot path for a new external effect: the scope
        exclusion check and PREPARED insertion share one writer transaction,
        eliminating both duplicate durable wrappers and the prior TOCTOU gap.
        """
        intent_id = str(intent_field(intent, "intent_id"))
        run_id = str(intent_field(intent, "run_id"))
        lifetime_id = intent_field(intent, "lifetime_id")
        phases = tuple(
            phase.value for phase in EffectIntentPhase if not phase.terminal
        )
        with self.backend.write_session() as tx:
            current_encoded = tx.read(intent_id)
            current = (
                self.codec.decode_record(current_encoded)
                if current_encoded is not None
                else None
            )
            current_event = (
                tx.read_event_head(intent_id)
                if current_encoded is not None
                else None
            )
            if current is not None and (
                current_event is None
                or effect_record_from_event(current_event) != current
            ):
                raise RuntimeError(
                    "effect projection diverged from causal Event Journal: "
                    + intent_id
                )

            pending_encoded = tx.scan_scope_phases(
                run_id=run_id,
                lifetime_id=lifetime_id,
                phases=phases,
                exclude_intent_id=intent_id,
            )
            if pending_encoded:
                pending = tuple(
                    self.codec.decode_record(row) for row in pending_encoded
                )
                summary = ",".join(
                    f"{intent_field(record_field(row, 'intent'), 'intent_id')}:"
                    f"{record_field(row, 'phase').value}"
                    for row in pending[:8]
                )
                raise PendingEffectRecoveryRequired(
                    f"run/lifetime has {len(pending)} unresolved external "
                    f"effect intent(s): {summary}"
                )

            result = prepare_transition(current, intent)
            if result.created:
                event = effect_record_event(result.record)
                if not tx.insert(
                    self.codec.encode_record(result.record),
                    event=event,
                ):
                    raise EffectIntentConflict(
                        f"effect intent concurrent insert conflict: {intent_id}"
                    )
            tx.commit()
            return result

    def _transition(self, intent_id: str, transition) -> NoetriumUnit:
        with self.backend.write_session() as tx:
            encoded = tx.read(intent_id)
            if encoded is None:
                raise self._unknown(intent_id)
            current = self.codec.decode_record(encoded)
            current_event = tx.read_event_head(intent_id)
            if current_event is None or effect_record_from_event(current_event) != current:
                raise RuntimeError(
                    "effect projection diverged from causal Event Journal: "
                    + intent_id
                )
            desired = transition(current)
            if desired is not current:
                if record_field(desired, "intent") != record_field(current, "intent"):
                    raise RuntimeError(
                        "effect transition changed immutable intent identity"
                    )
                event = effect_record_event(
                    desired,
                    causal_parent=current_event,
                )
                if not tx.update(
                    self.codec.encode_transition(desired, prior=encoded),
                    event=event,
                    expected_event_digest=current_event.unit_digest,
                    expected_phase=record_field(current, "phase").value,
                    expected_effect_digest=record_field(
                        current, "effect_digest"
                    ),
                ):
                    raise EffectIntentConflict(
                        f"effect intent concurrent transition conflict: {intent_id}"
                    )
            tx.commit()
            return desired

    def record_result(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt | None,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        return self._transition(
            intent_id,
            lambda current: effect_transition(
                current,
                request_digest=request_digest,
                phase=EffectIntentPhase.RESULT_RECORDED,
                effect=effect,
                result_snapshot=result_snapshot,
            ),
        )

    def record_terminal_result(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
        result_snapshot: NoetriumUnit | None = None,
        consumption: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        """Atomically persist provider result and its immediate terminal state.

        RESULT_RECORDED remains in the causal Event chain, but the projection
        reaches the terminal state in the same writer transaction. This removes
        a redundant FULL-sync boundary and the crash window between recording a
        provider conclusion and consuming/terminalizing that exact conclusion.
        """
        with self.backend.write_session() as tx:
            encoded = tx.read(intent_id)
            if encoded is None:
                raise self._unknown(intent_id)
            current = self.codec.decode_record(encoded)
            current_event = tx.read_event_head(intent_id)
            if current_event is None or effect_record_from_event(current_event) != current:
                raise RuntimeError(
                    "effect projection diverged from causal Event Journal: "
                    + intent_id
                )

            terminal_phases = {
                EffectIntentPhase.CONSUMED,
                EffectIntentPhase.NOT_APPLIED,
                EffectIntentPhase.INDETERMINATE,
            }
            if record_field(current, "phase") in terminal_phases:
                require_terminal_result_match(
                    current,
                    request_digest=request_digest,
                    effect=effect,
                    result_snapshot=result_snapshot,
                )
                if effect.certainty in {
                    EffectCertainty.EFFECT_CONFIRMED,
                    EffectCertainty.EFFECT_REJECTED,
                }:
                    if consumption is None:
                        raise EffectIntentConflict(
                            "resolved external effect requires completion evidence"
                        )
                    desired = consumed_transition(
                        current,
                        request_digest=request_digest,
                        consumption=consumption,
                    )
                elif effect.certainty is EffectCertainty.NO_EFFECT:
                    if consumption is not None:
                        raise EffectIntentConflict(
                            "NO_EFFECT terminal cannot carry consumption evidence"
                        )
                    desired = not_applied_transition(
                        current,
                        request_digest=request_digest,
                        effect=effect,
                    )
                elif effect.certainty is EffectCertainty.INDETERMINATE:
                    if consumption is not None:
                        raise EffectIntentConflict(
                            "INDETERMINATE terminal cannot carry consumption evidence"
                        )
                    desired = indeterminate_transition(
                        current,
                        request_digest=request_digest,
                        effect=effect,
                    )
                else:
                    raise EffectIntentConflict(
                        "unsupported terminal effect certainty"
                    )
                tx.commit()
                return desired

            result = effect_transition(
                current,
                request_digest=request_digest,
                phase=EffectIntentPhase.RESULT_RECORDED,
                effect=effect,
                result_snapshot=result_snapshot,
            )
            cursor = current
            cursor_encoded = encoded
            cursor_event = current_event
            if result is not current:
                result_event = effect_record_event(
                    result,
                    causal_parent=current_event,
                )
                result_encoded = self.codec.encode_transition(
                    result,
                    prior=encoded,
                )
                if not tx.update(
                    result_encoded,
                    event=result_event,
                    expected_event_digest=current_event.unit_digest,
                    expected_phase=record_field(current, "phase").value,
                    expected_effect_digest=record_field(
                        current, "effect_digest"
                    ),
                ):
                    raise EffectIntentConflict(
                        f"effect intent concurrent result conflict: {intent_id}"
                    )
                cursor = result
                cursor_encoded = result_encoded
                cursor_event = result_event

            if effect.certainty in {
                EffectCertainty.EFFECT_CONFIRMED,
                EffectCertainty.EFFECT_REJECTED,
            }:
                if consumption is None:
                    raise EffectIntentConflict(
                        "resolved external effect requires completion evidence"
                    )
                terminal = consumed_transition(
                    cursor,
                    request_digest=request_digest,
                    consumption=consumption,
                )
            elif effect.certainty is EffectCertainty.NO_EFFECT:
                if consumption is not None:
                    raise EffectIntentConflict(
                        "NO_EFFECT terminal cannot carry consumption evidence"
                    )
                terminal = not_applied_transition(
                    cursor,
                    request_digest=request_digest,
                    effect=effect,
                )
            elif effect.certainty is EffectCertainty.INDETERMINATE:
                if consumption is not None:
                    raise EffectIntentConflict(
                        "INDETERMINATE terminal cannot carry consumption evidence"
                    )
                terminal = indeterminate_transition(
                    cursor,
                    request_digest=request_digest,
                    effect=effect,
                )
            else:
                raise EffectIntentConflict("unsupported terminal effect certainty")

            if terminal is not cursor:
                terminal_event = effect_record_event(
                    terminal,
                    causal_parent=cursor_event,
                )
                terminal_encoded = self.codec.encode_transition(
                    terminal,
                    prior=cursor_encoded,
                )
                if not tx.update(
                    terminal_encoded,
                    event=terminal_event,
                    expected_event_digest=cursor_event.unit_digest,
                    expected_phase=record_field(cursor, "phase").value,
                    expected_effect_digest=record_field(
                        cursor, "effect_digest"
                    ),
                ):
                    raise EffectIntentConflict(
                        f"effect intent concurrent terminal conflict: {intent_id}"
                    )
            tx.commit()
            return terminal

    def record_reconciled(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        return self._transition(
            intent_id,
            lambda current: effect_transition(
                current,
                request_digest=request_digest,
                phase=EffectIntentPhase.RECONCILED,
                effect=effect,
                result_snapshot=result_snapshot,
            ),
        )

    def record_consumed(
        self,
        intent_id: str,
        *,
        request_digest: str,
        consumption: NoetriumUnit,
    ) -> NoetriumUnit:
        return self._transition(
            intent_id,
            lambda current: consumed_transition(
                current,
                request_digest=request_digest,
                consumption=consumption,
            ),
        )

    def record_not_applied(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
    ) -> NoetriumUnit:
        return self._transition(
            intent_id,
            lambda current: not_applied_transition(
                current,
                request_digest=request_digest,
                effect=effect,
            ),
        )

    def record_indeterminate(
        self,
        intent_id: str,
        *,
        request_digest: str,
        effect: EffectReceipt,
    ) -> NoetriumUnit:
        return self._transition(
            intent_id,
            lambda current: indeterminate_transition(
                current,
                request_digest=request_digest,
                effect=effect,
            ),
        )

    def unresolved_for_scope(
        self,
        *,
        run_id: str,
        lifetime_id: str | None,
        exclude_intent_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        phases = tuple(
            phase.value for phase in EffectIntentPhase if not phase.terminal
        )
        encoded = self.backend.scan_scope_phases(
            run_id=run_id,
            lifetime_id=lifetime_id,
            phases=phases,
            exclude_intent_id=exclude_intent_id,
        )
        return tuple(self.codec.decode_record(row) for row in encoded)

    def events_for_run(self, run_id: str) -> tuple[NoetriumUnit, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect event run_id must be non-empty text")
        return self.backend.scan_run_events(run_id=run_id)

    def verify_projection_rebuild(
        self,
        run_id: str,
    ) -> tuple[NoetriumUnit, ...]:
        """Fail-close unless latest rows are exactly derivable from Event Units."""

        events = self.events_for_run(run_id)
        latest: dict[str, NoetriumUnit] = {}
        for event in causal_topological_order(events):
            record = effect_record_from_event(event)
            intent = record_field(record, "intent")
            latest[str(intent_field(intent, "intent_id"))] = record

        projected = tuple(latest[key] for key in sorted(latest))
        materialized = tuple(
            sorted(
                self.records_for_run(run_id),
                key=lambda record: str(
                    intent_field(record_field(record, "intent"), "intent_id")
                ),
            )
        )
        if projected != materialized:
            raise RuntimeError(
                "effect latest-state projection diverged from causal Event Journal"
            )
        return projected

    def records_for_run(self, run_id: str) -> tuple[NoetriumUnit, ...]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("effect journal run_id must be non-empty text")
        encoded = self.backend.scan_run(run_id=run_id)
        return tuple(self.codec.decode_record(row) for row in encoded)


__all__ = ["EffectJournalCodec", "EffectIntentJournalRuntime"]
