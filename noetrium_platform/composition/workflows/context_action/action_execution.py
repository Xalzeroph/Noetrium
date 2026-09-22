from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort

from .action_contracts import PreparedSafeAction, SafeActionExecution
from .action_effect_provider import ActionEffectProviderOperations
from .action_execution_direct import execute_direct_action
from .action_execution_journal import JournaledActionExecutor
from .action_preparation import ActionPreparationCoordinator
from .action_reconciliation import ActionReconciliationPolicy
from .action_reconciliation_operations import ActionReconciliationOperations
from .effect_safety import EffectSafetyPolicy


class ActionExecutionCoordinator:
    """Select direct or durable-journal action flow; neither flow owns provider/runtime state."""

    def __init__(
        self,
        *,
        journal_ops: EffectIntentOperationPort | None,
        preparation: ActionPreparationCoordinator,
        effect_provider: ActionEffectProviderOperations,
        reconciliation: ActionReconciliationOperations,
        reconciliation_policy: ActionReconciliationPolicy,
        effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
    ) -> None:
        self._preparation = preparation
        self._effect_provider = effect_provider
        self._effect_policy = effect_policy
        self._journal_executor = (
            None
            if journal_ops is None
            else JournaledActionExecutor(
                journal_ops=journal_ops,
                preparation=preparation,
                effect_provider=effect_provider,
                reconciliation=reconciliation,
                reconciliation_policy=reconciliation_policy,
                effect_policy=effect_policy,
            )
        )

    def execute_prepared(self, prepared: PreparedSafeAction) -> SafeActionExecution:
        self._preparation.require_prepared(prepared)
        if self._journal_executor is None:
            return execute_direct_action(prepared, provider=self._effect_provider, effect_policy=self._effect_policy)
        return self._journal_executor.execute(prepared)


__all__ = ["ActionExecutionCoordinator"]
