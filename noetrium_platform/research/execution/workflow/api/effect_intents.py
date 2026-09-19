from __future__ import annotations

from typing import Protocol

from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentPrepareResult,
    EffectIntentRecord,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectReceipt, ExecutionContext, JsonValue, OperationResult


class EffectIntentOperationPort(Protocol):
    """Workflow-facing durable-effect intent operations, independent of journal backend."""

    @property
    def durability(self) -> str: ...

    @property
    def component_identity(self) -> ComponentIdentity: ...

    def inspect(
        self,
        intent: EffectIntent,
        context: ExecutionContext,
        *,
        stage: str = "read",
    ) -> tuple[EffectIntentRecord | None, OperationResult[JsonValue]]: ...

    def require_scope_clear(
        self,
        intent: EffectIntent,
        context: ExecutionContext,
        *,
        stage: str = "preflight",
    ) -> tuple[dict[str, JsonValue], OperationResult[JsonValue]]: ...

    def prepare(
        self,
        intent: EffectIntent,
        context: ExecutionContext,
    ) -> tuple[EffectIntentPrepareResult, OperationResult[JsonValue]]: ...

    def record_result(
        self,
        intent: EffectIntent,
        effect: EffectReceipt | None,
        context: ExecutionContext,
    ) -> tuple[EffectIntentRecord, OperationResult[JsonValue]]: ...

    def record_reconciled(
        self,
        intent: EffectIntent,
        effect: EffectReceipt,
        context: ExecutionContext,
    ) -> tuple[EffectIntentRecord, OperationResult[JsonValue]]: ...

    def record_consumed(
        self,
        intent: EffectIntent,
        consumption: EffectCompletionEvidence,
        context: ExecutionContext,
    ) -> tuple[EffectIntentRecord, OperationResult[JsonValue]]: ...

    def record_not_applied(
        self,
        intent: EffectIntent,
        effect: EffectReceipt,
        context: ExecutionContext,
    ) -> tuple[EffectIntentRecord, OperationResult[JsonValue]]: ...


__all__ = ["EffectIntentOperationPort"]
