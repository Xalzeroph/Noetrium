from __future__ import annotations

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionSafetyCapabilityMissing,
    DurablePreparedActionSession,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


class ActionRecoveryCapabilityGuard:
    """Verifies prepared-effect recovery capability before a journal-backed action starts."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        journal_durability: str | None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._environment_session = environment_session
        self._journal_durability = journal_durability
        self._validated = False

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def preflight(self, context: ExecutionContext) -> tuple[OperationResult[JsonValue], ...]:
        if self._journal_durability is None:
            return ()
        if self._validated:
            return ()
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.action_safety_preflight",
            operation_type="environment.action_safety_preflight",
            target=self._bound.component("environment"),
            payload={
                "required_capability": "durable_action_recovery",
                "journal_durability": self._journal_durability,
            },
            payload_schema="environment.action.safety_preflight.v1",
            handler=lambda request: self._require_crash_reconciliation_capability(),
        )
        self._dispatcher.require(operation)
        self._validated = True
        return (operation,)

    def _require_crash_reconciliation_capability(self) -> dict[str, JsonValue]:
        if not isinstance(self._environment_session, DurablePreparedActionSession):
            raise ActionSafetyCapabilityMissing(
                "journal-backed action execution requires prepared Environment recovery capability"
            )
        durability = getattr(self._environment_session, "action_recovery_durability", None)
        if self._journal_durability == "crash_durable" and durability != "crash_durable":
            raise ActionSafetyCapabilityMissing(
                "crash-durable effect journal requires crash-durable Environment recovery"
            )
        required = (
            "prepare_action_recovery",
            "execute_prepared_action",
            "reconcile_prepared_action",
        )
        if any(not callable(getattr(self._environment_session, name, None)) for name in required):
            raise ActionSafetyCapabilityMissing(
                "journal-backed action recovery requires prepare + execute + reconcile prepared-action capability"
            )
        return {"capability": "durable_action_recovery", "available": True}


__all__ = ["ActionRecoveryCapabilityGuard"]
