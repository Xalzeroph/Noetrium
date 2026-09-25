from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityRequest,
    DurablePreparedCapabilitySession,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, JsonValue, OperationResult
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort

from .capability_effect_contracts import CapabilityEffectIdentityConflict
from .capability_effect_validation import (
    require_capability_effect_result,
    require_capability_reconciliation,
)
from .capability_operations import CapabilityInvocationExecution, CapabilityOperationAdapter


class CapabilityEffectProviderOperations:
    """Provider-bound prepare/execute/reconcile operations; no WAL state authority."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        capability_operations: CapabilityOperationAdapter,
    ) -> None:
        self._dispatcher = dispatcher
        self._capability_operations = capability_operations

    @property
    def capability_operations(self) -> CapabilityOperationAdapter:
        return self._capability_operations

    def prepare_handle(
        self,
        *,
        session: DurablePreparedCapabilitySession,
        target: ComponentIdentity,
        request: CapabilityRequest,
    ) -> tuple[PreparedEffectHandle, OperationResult[JsonValue]]:
        dc = request.context.decision_cycle_id or request.context.span_id
        request_id = capability_effect_request_id(request)
        digest = capability_request_digest(request)
        operation = self._dispatcher.dispatch(
            root_context=request.context,
            operation_id=f"{dc}:capability.effect.prepare:{request_id}",
            operation_type="capability.effect.prepare",
            target=target,
            payload=request,
            payload_schema="capability.effect.prepare.v1",
            idempotency_key=request.idempotency_key,
            handler=lambda envelope: self._prepare_handle_payload(
                session,
                CapabilityRequest(
                    envelope.payload.capability_id,
                    envelope.payload.payload,
                    envelope.context,
                    envelope.payload.idempotency_key,
                ),
                request_id,
                digest,
            ),
            digest_output=False,
        )
        return self._dispatcher.require(operation), operation

    @staticmethod
    def _prepare_handle_payload(
        session: DurablePreparedCapabilitySession,
        request: CapabilityRequest,
        request_id: str,
        request_digest: str,
    ) -> PreparedEffectHandle:
        handle = session.prepare_capability_effect(request)
        if not isinstance(handle, PreparedEffectHandle):
            raise TypeError("prepare_capability_effect must return PreparedEffectHandle")
        if handle.request_id != request_id or handle.request_digest != request_digest:
            raise CapabilityEffectIdentityConflict("prepared capability handle identity mismatch")
        return handle

    def execute_prepared(
        self,
        *,
        session: DurablePreparedCapabilitySession,
        target: ComponentIdentity,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        handle: PreparedEffectHandle,
        invocation_ordinal: int,
    ) -> CapabilityInvocationExecution:
        return self._capability_operations.invoke(
            target=target,
            session=session,
            descriptor=descriptor,
            request=request,
            invocation_ordinal=invocation_ordinal,
            handler=lambda rebound: require_capability_effect_result(
                session.execute_prepared_capability(rebound, handle),
                descriptor=descriptor,
                request=rebound,
            ),
        )

    def reconcile(
        self,
        *,
        session: DurablePreparedCapabilitySession,
        target: ComponentIdentity,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        handle: PreparedEffectHandle,
    ) -> tuple[CapabilityEffectReconciliationResult, OperationResult[JsonValue]]:
        dc = request.context.decision_cycle_id or request.context.span_id
        operation = self._dispatcher.dispatch(
            root_context=request.context,
            operation_id=f"{dc}:capability.effect.reconcile:{handle.request_id}",
            operation_type="capability.effect.reconcile",
            target=target,
            payload=handle,
            payload_schema="capability.effect.reconcile.v1",
            idempotency_key=request.idempotency_key,
            handler=lambda envelope: require_capability_reconciliation(
                session.reconcile_prepared_capability(handle, envelope.context),
                descriptor=descriptor,
                request=request,
            ),
            digest_output=False,
        )
        return self._dispatcher.require(operation), operation


__all__ = ["CapabilityEffectProviderOperations"]
