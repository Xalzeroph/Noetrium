from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import OperationSemanticPolicyViolation
from noetrium_platform.capabilities.participant.core.api.runtime_operations import participant_operation_verb


class ProtectedOperationSemanticPolicy:
    """Platform-wide idempotency requirements for durable or side-effecting operations."""

    IDEMPOTENCY_REQUIRED = frozenset({
        "environment.action_recovery.prepare",
        "environment.act",
        "environment.act_prepared",
        "environment.reconcile",
        "environment.reconcile_prepared_action",
        "environment.action_intent.prepare",
        "environment.action_intent.result_record",
        "environment.action_intent.reconciled",
        "environment.action_intent.consumed",
        "environment.action_intent.not_applied",
        "method.task_completed",
        "run.checkpoint.publish",
        "method.restore",
        "environment.restore",
        "capability.effect.prepare",
        "capability.effect.reconcile",
        "effect.intent.prepare",
        "effect.intent.result_record",
        "effect.intent.reconciled",
        "effect.intent.consumed",
        "effect.intent.not_applied",
        "participant.message.route",
    })

    @classmethod
    def validate(cls, operation_type: str, idempotency_key: str | None) -> None:
        protected = (
            operation_type in cls.IDEMPOTENCY_REQUIRED
            or participant_operation_verb(operation_type) == "restore"
        )
        if protected and (not isinstance(idempotency_key, str) or not idempotency_key.strip()):
            raise OperationSemanticPolicyViolation(
                f"protected operation requires stable idempotency key: {operation_type}"
            )


__all__ = ["ProtectedOperationSemanticPolicy"]
