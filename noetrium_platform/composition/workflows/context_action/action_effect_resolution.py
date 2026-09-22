from __future__ import annotations

from noetrium_platform.capabilities.environment.runtime.api import ActionRecoveryRequired, ActionRequest, ActionResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from .action_effect_provider import ActionEffectProviderOperations
from .effect_safety import EffectSafetyPolicy


def resolve_action_result(
    *,
    provider: ActionEffectProviderOperations,
    effect_policy: type[EffectSafetyPolicy],
    result: ActionResult,
    request: ActionRequest,
    context: ExecutionContext,
) -> tuple[ActionResult, tuple[OperationResult[JsonValue], ...]]:
    if not effect_policy.needs_reconciliation(result.effect):
        return result, ()
    if result.effect is None:
        raise ActionRecoveryRequired(
            "Environment action returned no EffectReceipt; continuation cannot be proven safe"
        )
    reconciled, operation = provider.reconcile_effect(request, result, context)
    return reconciled, (operation,)


__all__ = ["resolve_action_result"]
