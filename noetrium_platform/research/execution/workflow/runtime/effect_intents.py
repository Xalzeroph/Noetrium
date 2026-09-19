from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentJournal,
    EffectIntentPrepareResult,
    EffectIntentRecord,
    PendingEffectRecoveryRequired,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectReceipt, ExecutionContext, JsonValue, OperationResult

from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


EFFECT_JOURNAL_IDENTITY = ComponentIdentity(
    "platform.effect_intent_journal",
    "effect_intent_journal",
    "1",
    "1",
    "effect-journal-v1",
)


class EffectIntentOperations:
    """Provider-agnostic Operation adapter over an EffectIntentJournal."""

    def __init__(self, dispatcher: OperationDispatchPort, journal: EffectIntentJournal) -> None:
        self._dispatcher = dispatcher
        self._effect_journal = journal

    @property
    def durability(self) -> str:
        return self._effect_journal.durability

    @property
    def component_identity(self) -> ComponentIdentity:
        return EFFECT_JOURNAL_IDENTITY

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def inspect(self, intent: EffectIntent, context: ExecutionContext, *, stage: str = "read"):
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.inspect:{stage}:{intent.intent_id}",
            operation_type="effect.intent.inspect",
            target=EFFECT_JOURNAL_IDENTITY,
            payload={"intent_id": intent.intent_id},
            payload_schema="effect.intent.inspect.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.load(str(request.payload["intent_id"])),
        )
        return self._dispatcher.require(operation), operation

    def require_scope_clear(self, intent: EffectIntent, context: ExecutionContext, *, stage: str = "preflight"):
        dc = self._dc(context)
        payload = {
            "run_id": intent.run_id,
            "lifetime_id": intent.lifetime_id,
            "exclude_intent_id": intent.intent_id,
        }
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.pending_check:{stage}:{intent.intent_id}",
            operation_type="effect.intent.pending_check",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=payload,
            payload_schema="effect.intent.pending_check.v1",
            handler=lambda request: self._require_scope_clear_payload(request.payload),
        )
        return self._dispatcher.require(operation), operation

    def _require_scope_clear_payload(self, payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        pending = self._effect_journal.unresolved_for_scope(
            run_id=str(payload["run_id"]),
            lifetime_id=payload.get("lifetime_id"),
            exclude_intent_id=str(payload["exclude_intent_id"]),
        )
        if pending:
            summary = ",".join(f"{row.intent.intent_id}:{row.phase.value}" for row in pending[:8])
            raise PendingEffectRecoveryRequired(
                f"run/lifetime has {len(pending)} unresolved external effect intent(s): {summary}"
            )
        return {"pending": 0, "scope": "run+lifetime"}

    def prepare(self, intent: EffectIntent, context: ExecutionContext):
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.prepare:{intent.intent_id}",
            operation_type="effect.intent.prepare",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=intent,
            payload_schema="effect.intent.prepare.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.prepare(request.payload),
        )
        return self._dispatcher.require(operation), operation

    def record_result(self, intent: EffectIntent, effect: EffectReceipt | None, context: ExecutionContext):
        dc = self._dc(context)
        payload = {"intent_id": intent.intent_id, "request_digest": intent.request_digest, "effect": effect}
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.result:{intent.intent_id}",
            operation_type="effect.intent.result_record",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=payload,
            payload_schema="effect.intent.result.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.record_result(
                request.payload["intent_id"],
                request_digest=request.payload["request_digest"],
                effect=request.payload["effect"],
            ),
        )
        return self._dispatcher.require(operation), operation

    def record_reconciled(self, intent: EffectIntent, effect: EffectReceipt, context: ExecutionContext):
        dc = self._dc(context)
        payload = {"intent_id": intent.intent_id, "request_digest": intent.request_digest, "effect": effect}
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.reconciled:{intent.intent_id}",
            operation_type="effect.intent.reconciled",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=payload,
            payload_schema="effect.intent.reconciled.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.record_reconciled(
                request.payload["intent_id"],
                request_digest=request.payload["request_digest"],
                effect=request.payload["effect"],
            ),
        )
        return self._dispatcher.require(operation), operation

    def record_consumed(
        self,
        intent: EffectIntent,
        consumption: EffectCompletionEvidence,
        context: ExecutionContext,
    ):
        dc = self._dc(context)
        payload = {
            "intent_id": intent.intent_id,
            "request_digest": intent.request_digest,
            "consumption": consumption,
        }
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.consumed:{intent.intent_id}",
            operation_type="effect.intent.consumed",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=payload,
            payload_schema="effect.intent.consumed.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.record_consumed(
                request.payload["intent_id"],
                request_digest=request.payload["request_digest"],
                consumption=request.payload["consumption"],
            ),
        )
        return self._dispatcher.require(operation), operation

    def record_not_applied(self, intent: EffectIntent, effect: EffectReceipt, context: ExecutionContext):
        dc = self._dc(context)
        payload = {"intent_id": intent.intent_id, "request_digest": intent.request_digest, "effect": effect}
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:effect.intent.not_applied:{intent.intent_id}",
            operation_type="effect.intent.not_applied",
            target=EFFECT_JOURNAL_IDENTITY,
            payload=payload,
            payload_schema="effect.intent.not_applied.v1",
            idempotency_key=intent.intent_id,
            handler=lambda request: self._effect_journal.record_not_applied(
                request.payload["intent_id"],
                request_digest=request.payload["request_digest"],
                effect=request.payload["effect"],
            ),
        )
        return self._dispatcher.require(operation), operation


__all__ = ["EFFECT_JOURNAL_IDENTITY", "EffectIntentOperations"]
