from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationResult

from .action_contracts import PreparedSafeAction, SafeActionExecution
from .action_effect_provider import ActionEffectProviderOperations
from .action_effect_resolution import resolve_action_result
from .effect_safety import EffectSafetyPolicy


def execute_direct_action(
    prepared: PreparedSafeAction,
    *,
    provider: ActionEffectProviderOperations,
    effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
) -> SafeActionExecution:
    request = prepared.request
    rows: list[OperationResult[JsonValue]] = list(prepared.operation_results)
    result, operation = provider.dispatch_act(request, request.context)
    rows.append(operation)
    result, reconciliation = resolve_action_result(
        provider=provider,
        effect_policy=effect_policy,
        result=result,
        request=request,
        context=request.context,
    )
    rows.extend(reconciliation)
    return SafeActionExecution(result, tuple(rows))


__all__ = ["execute_direct_action"]
