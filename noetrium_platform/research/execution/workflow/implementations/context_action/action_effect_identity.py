from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, PreparedEffectHandle
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, action_request_digest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity


def build_action_effect_intent(
    request: ActionRequest,
    *,
    operation_id: str,
    provider_component: ComponentIdentity,
    recovery_handle: PreparedEffectHandle | None = None,
) -> EffectIntent:
    return EffectIntent.build(
        request_id=request.action_id,
        request_digest=action_request_digest(request),
        operation_id=operation_id,
        provider_component=provider_component,
        context=request.context,
        source_generation=request.context.generation("environment"),
        recovery_handle=recovery_handle,
        intent_namespace="environment-effect",
    )


__all__ = ["build_action_effect_intent"]
