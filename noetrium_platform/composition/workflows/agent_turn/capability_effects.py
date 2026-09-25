from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor, CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectClass
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort, OperationDispatchPort

from .capability_effect_contracts import CapabilityEffectExecution, UnsafeEffectfulCapability
from .capability_effect_existing_flow import resolve_existing_capability_effect
from .capability_effect_identity import build_capability_effect_intent
from .capability_effect_new_flow import execute_new_capability_effect
from .capability_effect_provider import CapabilityEffectProviderOperations
from .capability_effect_validation import require_durable_capability_session
from .capability_operations import CapabilityOperationAdapter


class CapabilityEffectExecutor:
    """Selects the crash-safe existing/new effect flow; phase semantics live in collaborators."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        effect_intents: EffectIntentOperationPort,
        capability_operations: CapabilityOperationAdapter,
    ) -> None:
        self._intent_operations = effect_intents
        self._provider = CapabilityEffectProviderOperations(dispatcher, capability_operations)

    def invoke(
        self,
        *,
        target: ComponentIdentity,
        session: object,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        consumer_component: ComponentIdentity,
        invocation_ordinal: int = 0,
    ) -> CapabilityEffectExecution:
        if descriptor.effect_class not in {EffectClass.RECONCILABLE, EffectClass.NON_IDEMPOTENT}:
            raise ValueError(
                "CapabilityEffectExecutor is only for reconciliable/non-idempotent capabilities"
            )
        if not isinstance(request.idempotency_key, str) or not request.idempotency_key.strip():
            raise UnsafeEffectfulCapability(
                "effectful capability invocation requires idempotency_key"
            )

        durable = require_durable_capability_session(session)
        invoke_operation_id = self._provider.capability_operations.operation_id(
            request,
            invocation_ordinal=invocation_ordinal,
        )
        probe = build_capability_effect_intent(request, target, invoke_operation_id)
        existing, inspect_operation = self._intent_operations.inspect(probe, request.context)
        prefix = (inspect_operation,)
        if existing is not None:
            return resolve_existing_capability_effect(
                intent_operations=self._intent_operations,
                provider=self._provider,
                existing=existing,
                probe=probe,
                session=durable,
                target=target,
                descriptor=descriptor,
                request=request,
                consumer_component=consumer_component,
                completion_operation_id=invoke_operation_id,
                prefix_operations=prefix,
            )
        return execute_new_capability_effect(
            intent_operations=self._intent_operations,
            provider=self._provider,
            probe=probe,
            session=durable,
            target=target,
            descriptor=descriptor,
            request=request,
            consumer_component=consumer_component,
            invoke_operation_id=invoke_operation_id,
            invocation_ordinal=invocation_ordinal,
            prefix_operations=prefix,
        )


__all__ = ["CapabilityEffectExecutor"]
