from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentPhase, EffectIntentRecord
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .action_authorization import ActionAuthorizationBuilder
from .action_capability import ActionRecoveryCapabilityGuard
from .action_contracts import PreparedSafeAction
from noetrium_platform.research.execution.workflow.api import (
    EffectIntentOperationPort,
    OperationDispatchPort,
)
from .action_slot_guard import ActionSlotGuard, ActionSlotInspection
from noetrium_platform.capabilities.participant.core.api import BoundParticipants


class ActionPreparationCoordinator:
    """Composition façade for action safety preparation.

    Capability proof, logical-slot guards, and exact authorization are deliberately owned by
    separate collaborators.  This class carries no mutable action state of its own.
    """

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        journal_ops: EffectIntentOperationPort | None,
        journal_durability: str | None,
    ) -> None:
        self._capability = ActionRecoveryCapabilityGuard(
            dispatcher,
            bound,
            environment_session,
            journal_durability=journal_durability,
        )
        self._slots = ActionSlotGuard(
            dispatcher,
            bound,
            journal_ops=journal_ops,
            journal_durability=journal_durability,
        )
        self._authorization = ActionAuthorizationBuilder(
            dispatcher,
            bound,
            environment_session,
            journal_ops=journal_ops,
            journal_durability=journal_durability,
        )

    def preflight_capability(self, context: ExecutionContext) -> tuple[OperationResult[JsonValue], ...]:
        return self._capability.preflight(context)

    def preflight_action_slot(
        self, *, action_type: str, action_payload: object, context: ExecutionContext
    ) -> ActionSlotInspection:
        inspection = self._slots.preflight_slot(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )
        return replace(
            inspection,
            operation_results=(
                self._capability.preflight(context)
                + inspection.operation_results
            ),
        )

    def prepare_action(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
        capability_checked: bool = False,
    ) -> PreparedSafeAction:
        prepared = self._authorization.prepare(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )
        if capability_checked:
            return prepared
        return replace(
            prepared,
            operation_results=self._capability.preflight(context) + prepared.operation_results,
        )

    def require_prepared(self, prepared: PreparedSafeAction) -> None:
        self._authorization.require_prepared(prepared)

    def guard_existing_intent(
        self, phase: EffectIntentPhase, context: ExecutionContext
    ) -> OperationResult[JsonValue] | None:
        return self._slots.guard_existing_intent(phase, context)


__all__ = ["ActionPreparationCoordinator"]
