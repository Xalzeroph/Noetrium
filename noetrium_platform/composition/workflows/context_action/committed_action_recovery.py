from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentRecord
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRecoveryRequired,
    ActionScientificCommitContradiction,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, ExecutionContext, JsonValue, OperationResult

from .action_contracts import SafeActionExecution
from .action_effect_provider import ActionEffectProviderOperations
from .action_reconciliation import ActionReconciliationPolicy
from .action_reconciliation_operations import ActionReconciliationOperations
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort
from .effect_safety import EffectSafetyPolicy


class CommittedActionRecovery:
    """Reconciles external effect state after Method authority proves completion.

    This collaborator has no Method API and no Environment ``act`` capability.  It can
    only inspect/update the action journal and invoke the read/reconcile effect boundary.
    """

    def __init__(
        self,
        journal_ops: EffectIntentOperationPort,
        effect_provider: ActionEffectProviderOperations,
        reconciliation: ActionReconciliationOperations,
        reconciliation_policy: ActionReconciliationPolicy,
        *,
        effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
    ) -> None:
        self._journal_ops = journal_ops
        self._effect_provider = effect_provider
        self._reconciliation = reconciliation
        self._reconciliation_policy = reconciliation_policy
        self._effect_policy = effect_policy

    def recover_durable(
        self, existing: EffectIntentRecord, context: ExecutionContext
    ) -> SafeActionExecution:
        intent = existing.intent
        handle = intent.recovery_handle
        if handle is None:
            raise ActionRecoveryRequired(
                "committed-method recovery has no durable provider recovery handle"
            )
        refreshed, inspect_operation = self._journal_ops.inspect(intent, context, stage="commit-recovery")
        if refreshed is None or refreshed.intent.intent_id != intent.intent_id or refreshed.phase.terminal:
            raise ActionRecoveryRequired(
                "action intent changed while committed-method recovery was being prepared"
            )
        existing = refreshed
        rows: list[OperationResult[JsonValue]] = [inspect_operation]
        if (
            existing.effect is not None
            and not self._effect_policy.needs_reconciliation(existing.effect)
            and existing.effect.certainty is EffectCertainty.NO_EFFECT
        ):
            raise ActionScientificCommitContradiction(
                "method completion is committed but journal contains authoritative NO_EFFECT proof"
            )

        reconciliation, operation = self._effect_provider.reconcile_prepared_handle(handle, context)
        reconciliation = self._reconciliation_policy.validate_disposition(reconciliation)
        rows.append(operation)
        result, operation = self._reconciliation.committed_method_consistency(
            existing_effect=existing.effect,
            reconciliation=reconciliation,
            context=context,
        )
        rows.append(operation)
        effect = self._effect_policy.require_resolved(result.effect)
        if existing.effect is None or self._effect_policy.needs_reconciliation(existing.effect):
            _, operation = self._journal_ops.record_reconciled(intent, effect, context)
            rows.append(operation)
        diagnostics = dict(result.diagnostics)
        diagnostics["study_recovery"] = "method_completion_already_committed"
        diagnostics["action_recovery_source"] = "durable_provider_handle"
        return SafeActionExecution(
            replace(result, diagnostics=diagnostics), tuple(rows), replayed_from_intent=True
        )



__all__ = ["CommittedActionRecovery"]
