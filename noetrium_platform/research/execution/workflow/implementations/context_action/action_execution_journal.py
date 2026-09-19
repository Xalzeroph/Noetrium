from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRecoveryRequired,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort

from .action_contracts import PreparedSafeAction, SafeActionExecution
from .action_effect_provider import ActionEffectProviderOperations
from .action_effect_resolution import resolve_action_result
from .action_preparation import ActionPreparationCoordinator
from .action_reconciliation import ActionReconciliationPolicy
from .action_reconciliation_operations import ActionReconciliationOperations
from .effect_safety import EffectSafetyPolicy


class JournaledActionExecutor:
    """Owns journal-backed action sequencing; provider effects and policy stay external."""

    def __init__(
        self,
        *,
        journal_ops: EffectIntentOperationPort,
        preparation: ActionPreparationCoordinator,
        effect_provider: ActionEffectProviderOperations,
        reconciliation: ActionReconciliationOperations,
        reconciliation_policy: ActionReconciliationPolicy,
        effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
    ) -> None:
        self._journal_ops = journal_ops
        self._preparation = preparation
        self._effect_provider = effect_provider
        self._reconciliation = reconciliation
        self._reconciliation_policy = reconciliation_policy
        self._effect_policy = effect_policy

    def execute(self, prepared: PreparedSafeAction) -> SafeActionExecution:
        intent = self._require_intent(prepared)
        context = prepared.request.context
        rows: list[OperationResult[JsonValue]] = list(prepared.operation_results)
        prepared_record, operation = self._journal_ops.prepare(intent, context)
        rows.append(operation)
        guard = self._preparation.guard_existing_intent(prepared_record.record.phase, context)
        if guard is not None:
            rows.append(guard)
        if prepared_record.created:
            return self._execute_new(prepared, rows)
        return self._reconcile_existing(prepared, rows)

    def _reconcile_existing(
        self,
        prepared: PreparedSafeAction,
        rows: list[OperationResult[JsonValue]],
    ) -> SafeActionExecution:
        request = prepared.request
        intent = self._require_intent(prepared)
        handle = self._require_recovery_handle(intent)
        reconciliation, operation = self._effect_provider.reconcile_prepared_handle(
            handle,
            request.context,
        )
        reconciliation = self._reconciliation_policy.validate(request, reconciliation)
        rows.append(operation)
        self._record_reconciliation(intent, reconciliation, request.context, rows)
        result, operation = self._reconciliation.decide_continuation(
            reconciliation,
            request.context,
        )
        rows.append(operation)
        return SafeActionExecution(result, tuple(rows), replayed_from_intent=True)

    def _execute_new(
        self,
        prepared: PreparedSafeAction,
        rows: list[OperationResult[JsonValue]],
    ) -> SafeActionExecution:
        request = prepared.request
        context = request.context
        intent = self._require_intent(prepared)
        handle = self._require_recovery_handle(intent)
        result, operation = self._effect_provider.dispatch_prepared_act(
            request,
            handle,
            context,
        )
        rows.append(operation)
        _, operation = self._journal_ops.record_result(intent, result.effect, context)
        rows.append(operation)

        if result.effect is None:
            return self._resolve_missing_effect(prepared, rows)

        result, reconciliation_rows = resolve_action_result(
            provider=self._effect_provider,
            effect_policy=self._effect_policy,
            result=result,
            request=request,
            context=context,
        )
        rows.extend(reconciliation_rows)
        if reconciliation_rows:
            _, operation = self._journal_ops.record_reconciled(
                intent,
                self._effect_policy.require_resolved(result.effect),
                context,
            )
            rows.append(operation)
        return SafeActionExecution(result, tuple(rows))

    def _resolve_missing_effect(
        self,
        prepared: PreparedSafeAction,
        rows: list[OperationResult[JsonValue]],
    ) -> SafeActionExecution:
        request = prepared.request
        intent = self._require_intent(prepared)
        handle = self._require_recovery_handle(intent)
        reconciliation, operation = self._effect_provider.reconcile_prepared_handle(
            handle,
            request.context,
        )
        reconciliation = self._reconciliation_policy.validate(request, reconciliation)
        rows.append(operation)
        self._record_reconciliation(intent, reconciliation, request.context, rows)
        result, operation = self._reconciliation.decide_continuation(
            reconciliation,
            request.context,
        )
        rows.append(operation)
        return SafeActionExecution(result, tuple(rows))

    def _record_reconciliation(
        self,
        intent: EffectIntent,
        reconciliation: ActionReconciliationResult,
        context: ExecutionContext,
        rows: list[OperationResult[JsonValue]],
    ) -> None:
        effect = self._reconciliation_policy.effect(reconciliation)
        if effect is None or reconciliation.disposition is ActionReconciliationDisposition.UNKNOWN:
            return
        effect = self._effect_policy.require_resolved(effect)
        if reconciliation.disposition is ActionReconciliationDisposition.NOT_APPLIED:
            _, operation = self._journal_ops.record_not_applied(intent, effect, context)
        else:
            _, operation = self._journal_ops.record_reconciled(intent, effect, context)
        rows.append(operation)

    @staticmethod
    def _require_intent(prepared: PreparedSafeAction) -> EffectIntent:
        if prepared.intent is None:
            raise ActionRecoveryRequired("journal-backed prepared action is missing its intent")
        return prepared.intent

    @staticmethod
    def _require_recovery_handle(intent: EffectIntent):
        if intent.recovery_handle is None:
            raise ActionRecoveryRequired("PREPARED effect intent is missing provider recovery handle")
        return intent.recovery_handle


__all__ = ["JournaledActionExecutor"]
