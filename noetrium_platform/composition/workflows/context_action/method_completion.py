from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.effect.api import EffectCompletionEvidence
from noetrium_platform.capabilities.environment.runtime.api import ActionResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult, canonical_digest
from noetrium_platform.capabilities.participant.method.api import (
    IdempotentTaskCompletionSession,
    MethodTaskCompletionReceipt,
    TaskCompletionReconciliationSession,
    TaskCompletionSafetyCapabilityMissing,
)

from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


@dataclass(frozen=True, slots=True)
class MethodCompletionMutation:
    receipt: MethodTaskCompletionReceipt | None
    operation: OperationResult[JsonValue]
    consumption: EffectCompletionEvidence


class MethodCompletionAdapter:
    """Owns Method task-completion operation encoding and receipt validation only."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        method_session: object,
        *,
        effect_journal_durability: str | None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._method_session = method_session
        self._effect_journal_durability = effect_journal_durability

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def preflight(self, context: ExecutionContext) -> OperationResult[JsonValue] | None:
        if self._effect_journal_durability != "crash_durable":
            return None
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:method.task_completion_safety_preflight",
            operation_type="method.task_completion_safety_preflight",
            target=self._bound.component("method"),
            payload={
                "required_capability": "idempotent_task_completion",
                "journal_durability": self._effect_journal_durability,
            },
            payload_schema="method.task_completion.safety_preflight.v1",
            handler=lambda request: self._require_idempotency(request.context),
        )
        self._dispatcher.require(operation)
        return operation

    def _require_idempotency(self, context: ExecutionContext) -> dict[str, JsonValue]:
        if not isinstance(self._method_session, IdempotentTaskCompletionSession):
            raise TaskCompletionSafetyCapabilityMissing(
                "crash-durable action recovery requires idempotent Method.task_completed capability"
            )
        key = self._method_session.task_completion_key(context)
        if not isinstance(key, str) or not key.strip():
            raise TaskCompletionSafetyCapabilityMissing(
                "Method.task_completion_key must return a stable non-empty string"
            )
        marker = getattr(self._method_session, "task_completion_idempotency", "")
        if not isinstance(marker, str) or not marker.strip():
            raise TaskCompletionSafetyCapabilityMissing(
                "Method task completion idempotency marker is missing"
            )
        return {"idempotency": marker, "key": key}

    def _completion_key(self, context: ExecutionContext) -> str:
        dc = self._dc(context)
        if isinstance(self._method_session, IdempotentTaskCompletionSession):
            return self._method_session.task_completion_key(context)
        return f"operation:{context.run_id}:{dc}:method.task_completed"

    def complete(
        self,
        action_result: ActionResult,
        context: ExecutionContext,
    ) -> MethodCompletionMutation:
        dc = self._dc(context)
        completion_key = self._completion_key(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:method.task_completed",
            operation_type="method.task_completed",
            target=self._bound.component("method"),
            payload=action_result,
            payload_schema="method.task_completed.request.v1",
            idempotency_key=completion_key,
            handler=lambda request: self._method_session.task_completed(
                request.payload, request.context
            ),
        )
        receipt = self._dispatcher.require(operation)
        self._validate_receipt(receipt, completion_key, durable=isinstance(
            self._method_session, IdempotentTaskCompletionSession
        ))
        effective_key = receipt.completion_key if receipt is not None else completion_key
        consumption = self._consumption(
            effective_key,
            f"{dc}:method.task_completed",
            receipt.method_generation if receipt is not None else context.generation("method"),
        )
        return MethodCompletionMutation(receipt, operation, consumption)

    def reconcile(self, context: ExecutionContext) -> MethodCompletionMutation | None:
        if not isinstance(self._method_session, IdempotentTaskCompletionSession):
            return None
        if not isinstance(self._method_session, TaskCompletionReconciliationSession):
            return None
        dc = self._dc(context)
        completion_key = self._method_session.task_completion_key(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:method.task_completion_reconcile",
            operation_type="method.task_completion_reconcile",
            target=self._bound.component("method"),
            payload={"completion_key": completion_key},
            payload_schema="method.task_completion.reconcile.v1",
            idempotency_key=completion_key,
            handler=lambda request: self._method_session.reconcile_task_completion(
                str(request.payload["completion_key"]), request.context
            ),
        )
        receipt = self._dispatcher.require(operation)
        if receipt is None:
            return None
        self._validate_receipt(receipt, completion_key, durable=True)
        return MethodCompletionMutation(
            receipt,
            operation,
            self._consumption(
                receipt.completion_key,
                f"{dc}:method.task_completed",
                receipt.method_generation,
            ),
        )

    @staticmethod
    def _validate_receipt(
        receipt: object,
        expected_key: str,
        *,
        durable: bool,
    ) -> None:
        if receipt is not None and not isinstance(receipt, MethodTaskCompletionReceipt):
            raise TypeError("method task completion must return MethodTaskCompletionReceipt or None")
        if durable and receipt is not None and receipt.completion_key != expected_key:
            raise RuntimeError(
                "MethodTaskCompletionReceipt.completion_key does not match method idempotency identity"
            )

    def _consumption(
        self,
        completion_key: str,
        completion_operation_id: str,
        method_generation: str | None,
    ) -> EffectCompletionEvidence:
        return EffectCompletionEvidence(
            completion_key=completion_key,
            completion_operation_id=completion_operation_id,
            consumer_component_digest=canonical_digest(self._bound.component("method")),
            consumer_generation=method_generation,
        )


__all__ = ["MethodCompletionAdapter", "MethodCompletionMutation"]
