from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityProviderSession,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, JsonValue, OperationResult, canonical_digest

from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


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
        operation = self._dispatcher.dispatch(
            root_context=request.context,
            operation_id=self.operation_id(request, invocation_ordinal=invocation_ordinal),
            operation_type="capability.invoke",
            target=target,
            payload=request,
            payload_schema=descriptor.request_schema,
            idempotency_key=request.idempotency_key,
            handler=lambda envelope: (handler or session.invoke)(
                CapabilityRequest(
                    envelope.payload.capability_id,
                    envelope.payload.payload,
                    envelope.context,
                    envelope.payload.idempotency_key,
                )
            ),
        )
        result = self._dispatcher.require(operation)
        if not isinstance(result, CapabilityResult):
            raise TypeError("CapabilityProviderSession invocation must return CapabilityResult")
        if result.capability_id != request.capability_id:
            raise ValueError("capability provider returned mismatched capability_id")
        return CapabilityInvocationExecution(result, operation)


__all__ = ["CapabilityInvocationExecution", "CapabilityOperationAdapter"]
