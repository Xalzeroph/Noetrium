from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityProviderSession,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectClass, JsonValue, OperationResult, canonical_digest

from noetrium_platform.research.execution.operation.api import OperationEffectProfile
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort, OperationEffectBinding


@dataclass(frozen=True, slots=True)
class CapabilityInvocationExecution:
    result: CapabilityResult
    operation: OperationResult[JsonValue]


class CapabilityOperationAdapter:
    """Encodes one already-routed capability invocation as a Kernel operation."""

    def __init__(self, dispatcher: OperationDispatchPort) -> None:
        self._dispatcher = dispatcher

    @staticmethod
    def operation_id(request: CapabilityRequest, *, invocation_ordinal: int = 0) -> str:
        dc = request.context.decision_cycle_id or request.context.span_id
        if isinstance(request.idempotency_key, str) and request.idempotency_key.strip():
            slot = canonical_digest(request.idempotency_key)[:16]
            return f"{dc}:capability.invoke:{request.capability_id}:key:{slot}"
        if invocation_ordinal <= 0:
            return f"{dc}:capability.invoke:{request.capability_id}"
        return f"{dc}:capability.invoke:{request.capability_id}:call:{invocation_ordinal}"

    def invoke(
        self,
        *,
        target: ComponentIdentity,
        session: CapabilityProviderSession,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        invocation_ordinal: int = 0,
        handler: Callable[[CapabilityRequest], CapabilityResult] | None = None,
    ) -> CapabilityInvocationExecution:
        effect_binding = None
        if descriptor.effect_class is not EffectClass.PURE:
            request_id = capability_effect_request_id(request)
            effect_binding = OperationEffectBinding(
                OperationEffectProfile(descriptor.effect_class.value),
                request_id,
                request_id,
                capability_request_digest(request),
            )

        def invoke_provider(envelope) -> CapabilityResult:
            rebound = CapabilityRequest(
                envelope.payload.capability_id,
                envelope.payload.payload,
                envelope.context,
                envelope.payload.idempotency_key,
            )
            result = (handler or session.invoke)(rebound)
            if not isinstance(result, CapabilityResult):
                raise TypeError(
                    "CapabilityProviderSession invocation must return CapabilityResult"
                )
            if result.capability_id != request.capability_id:
                raise ValueError(
                    "capability provider returned mismatched capability_id"
                )
            if descriptor.effect_class is EffectClass.PURE and result.effect is not None:
                raise ValueError("PURE capability returned an external-effect receipt")
            return result

        operation = self._dispatcher.dispatch(
            root_context=request.context,
            operation_id=self.operation_id(request, invocation_ordinal=invocation_ordinal),
            operation_type="capability.invoke",
            target=target,
            payload=request,
            payload_schema=descriptor.request_schema,
            idempotency_key=request.idempotency_key,
            effect_binding=effect_binding,
            effect_projector=lambda output: (
                () if output.effect is None else (output.effect,)
            ),
            handler=invoke_provider,
        )
        result = self._dispatcher.require(operation)
        if not isinstance(result, CapabilityResult):
            raise TypeError("CapabilityProviderSession invocation must return CapabilityResult")
        if result.capability_id != request.capability_id:
            raise ValueError("capability provider returned mismatched capability_id")
        return CapabilityInvocationExecution(result, operation)


__all__ = ["CapabilityInvocationExecution", "CapabilityOperationAdapter"]
