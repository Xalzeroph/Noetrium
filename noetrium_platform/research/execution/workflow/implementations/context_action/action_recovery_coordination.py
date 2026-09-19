from __future__ import annotations
from noetrium_platform.capabilities.environment.runtime.api import ActionRecoveryRequired
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from .action_contracts import SafeActionExecution
from .action_preparation import ActionPreparationCoordinator
from .committed_action_recovery import CommittedActionRecovery

class ActionCommittedRecoveryCoordinator:
    """Stateless recovery from authoritative effect-journal records."""
    def __init__(self,preparation:ActionPreparationCoordinator,recovery:CommittedActionRecovery|None)->None:
        self._preparation=preparation; self._recovery=recovery
    def recover(self,*,action_type:str,action_payload:object,context:ExecutionContext)->SafeActionExecution:
        inspection=self._preparation.preflight_action_slot(action_type=action_type,action_payload=action_payload,context=context)
        existing=inspection.nonterminal
        if existing is None or self._recovery is None: raise ActionRecoveryRequired("committed-method recovery requires a non-terminal action intent")
        if existing.intent.recovery_handle is None: raise ActionRecoveryRequired("committed-method recovery requires a durable provider recovery handle")
        execution=self._recovery.recover_durable(existing,context)
        return SafeActionExecution(execution.result,inspection.operation_results+execution.operation_results,replayed_from_intent=True)

__all__=["ActionCommittedRecoveryCoordinator"]
