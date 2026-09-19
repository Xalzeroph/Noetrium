from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectCompletionEvidence, EffectIntentPhase
from noetrium_platform.capabilities.environment.runtime.api import ActionNotApplied, ActionRecoveryRequired
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .action_assembly import ActionSafetyAssembly
from .action_contracts import ActionSafetyPermit, PreparedSafeAction, SafeActionExecution
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from .effect_safety import EffectSafetyPolicy
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort, OperationDispatchPort


class SafeEnvironmentActionExecutor:
    """Public façade over the independently composed action-safety subsystem."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        effect_intents: EffectIntentOperationPort | None = None,
        effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
    ) -> None:
        self._effect_intents = effect_intents
        self._runtime = ActionSafetyAssembly(
            dispatcher,
            bound,
            environment_session,
            effect_intents=effect_intents,
            effect_policy=effect_policy,
        ).build()

    def preflight_capability(self, context: ExecutionContext) -> tuple[OperationResult[JsonValue], ...]:
        return self._runtime.preparation.preflight_capability(context)

    def preflight_action_slot(
        self, *, action_type: str, action_payload: object, context: ExecutionContext
    ):
        return self._runtime.preparation.preflight_action_slot(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )

    def prepare_action(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
        capability_checked: bool = False,
    ) -> PreparedSafeAction:
        return self._runtime.preparation.prepare_action(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
            capability_checked=capability_checked,
        )

    def confirm_trial_commit(
        self, *, action_type: str, action_payload: object,
        context: ExecutionContext, consumption: EffectCompletionEvidence,
    ) -> tuple[OperationResult[JsonValue], ...]:
        if self._effect_intents is None:
            return ()
        prepared=self.prepare_action(action_type=action_type,action_payload=action_payload,context=context,capability_checked=True)
        if prepared.intent is None:
            return tuple(prepared.operation_results)
        _,consumed=self._effect_intents.record_consumed(prepared.intent,consumption,context)
        return tuple(prepared.operation_results)+(consumed,)

    def recover_committed_action(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
    ) -> SafeActionExecution:
        return self._runtime.committed_recovery.recover(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
        )

    def execute(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
    ) -> SafeActionExecution:
        inspection = self.preflight_action_slot(action_type=action_type,action_payload=action_payload,context=context)
        early_rows = inspection.operation_results
        prepared = self.prepare_action(
            action_type=action_type,
            action_payload=action_payload,
            context=context,
            capability_checked=True,
        )
        execution = self.execute_prepared(prepared)
        return SafeActionExecution(
            execution.result,
            tuple(early_rows) + execution.operation_results,
            execution.replayed_from_intent,
        )

    def execute_prepared(self, prepared: PreparedSafeAction) -> SafeActionExecution:
        return self._runtime.execution.execute_prepared(prepared)


__all__ = [
    "ActionNotApplied",
    "ActionRecoveryRequired",
    "ActionSafetyPermit",
    "PreparedSafeAction",
    "SafeActionExecution",
    "SafeEnvironmentActionExecutor",
]
