from __future__ import annotations

from noetrium_platform.capabilities.environment.runtime.api import ActionReconciliationResult, ActionResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort

from .action_reconciliation import ActionReconciliationPolicy


class ActionReconciliationOperations:
    """Kernel operation boundary for pure reconciliation decisions."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        policy: ActionReconciliationPolicy,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._policy = policy

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def decide_continuation(
        self, reconciliation: ActionReconciliationResult, context: ExecutionContext
    ) -> tuple[ActionResult, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.action_recovery_decision",
            operation_type="environment.action_recovery_decision",
            target=self._bound.component("environment"),
            payload=reconciliation,
            payload_schema="environment.action.recovery_decision.v1",
            handler=lambda request: self._policy.require_continuation(request.payload),
            effect_projector=lambda output: (output.effect,) if output.effect is not None else (),
        )
        return self._dispatcher.require(operation), operation

    def committed_method_consistency(
        self,
        *,
        existing_effect,
        reconciliation: ActionReconciliationResult,
        context: ExecutionContext,
    ) -> tuple[ActionResult, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.action_commit_consistency",
            operation_type="environment.action_commit_consistency",
            target=self._bound.component("environment"),
            payload={"existing_effect": existing_effect, "reconciliation": reconciliation},
            payload_schema="environment.action_commit_consistency.v1",
            handler=lambda request: self._policy.require_committed_method_consistency(
                request.payload["existing_effect"], request.payload["reconciliation"]
            ),
            effect_projector=lambda output: (output.effect,) if output.effect is not None else (),
        )
        return self._dispatcher.require(operation), operation


__all__ = ["ActionReconciliationOperations"]
