from __future__ import annotations

from dataclasses import dataclass


from .action_effect_provider import ActionEffectProviderOperations
from .action_reconciliation import ActionReconciliationPolicy
from .action_reconciliation_operations import ActionReconciliationOperations
from .action_execution import ActionExecutionCoordinator
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort, OperationDispatchPort
from .action_preparation import ActionPreparationCoordinator
from .action_recovery_coordination import ActionCommittedRecoveryCoordinator
from .committed_action_recovery import CommittedActionRecovery
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from .effect_safety import EffectSafetyPolicy


@dataclass(frozen=True, slots=True)
class ActionSafetyRuntime:
    preparation: ActionPreparationCoordinator
    execution: ActionExecutionCoordinator
    committed_recovery: ActionCommittedRecoveryCoordinator


class ActionSafetyAssembly:
    """Single composition root for the external-action safety subsystem."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        effect_intents: EffectIntentOperationPort | None,
        effect_policy: type[EffectSafetyPolicy],
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._environment_session = environment_session
        self._effect_intents = effect_intents
        self._effect_policy = effect_policy

    def build(self) -> ActionSafetyRuntime:
        journal_ops = self._effect_intents
        journal_durability = journal_ops.durability if journal_ops is not None else None
        effect_provider = ActionEffectProviderOperations(
            self._dispatcher,
            self._bound,
            self._environment_session,
            effect_policy=self._effect_policy,
        )
        reconciliation_policy = ActionReconciliationPolicy(effect_policy=self._effect_policy)
        reconciliation = ActionReconciliationOperations(
            self._dispatcher, self._bound, reconciliation_policy
        )
        preparation = ActionPreparationCoordinator(
            self._dispatcher,
            self._bound,
            self._environment_session,
            journal_ops=journal_ops,
            journal_durability=journal_durability,
        )
        execution = ActionExecutionCoordinator(
            journal_ops=journal_ops,
            preparation=preparation,
            effect_provider=effect_provider,
            reconciliation=reconciliation,
            reconciliation_policy=reconciliation_policy,
            effect_policy=self._effect_policy,
        )
        committed = (
            CommittedActionRecovery(
                journal_ops,
                effect_provider,
                reconciliation,
                reconciliation_policy,
                effect_policy=self._effect_policy,
            )
            if journal_ops is not None
            else None
        )
        recovery = ActionCommittedRecoveryCoordinator(preparation, committed)
        return ActionSafetyRuntime(preparation, execution, recovery)


__all__ = ["ActionSafetyAssembly", "ActionSafetyRuntime"]
