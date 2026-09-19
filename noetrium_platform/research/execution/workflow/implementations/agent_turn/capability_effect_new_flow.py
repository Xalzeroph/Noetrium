from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    DurablePreparedCapabilitySession,
)
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, EffectReconciliationDisposition
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, JsonValue, OperationResult
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort

from .capability_effect_contracts import CapabilityEffectExecution
from .capability_effect_identity import build_capability_effect_intent
from .capability_effect_provider import CapabilityEffectProviderOperations
from .capability_effect_terminal import terminalize_capability_effect
from .capability_effect_validation import capability_effect_disposition


def execute_new_capability_effect(
    *,
    intent_operations: EffectIntentOperationPort,
    provider: CapabilityEffectProviderOperations,
    probe: EffectIntent,
    session: DurablePreparedCapabilitySession,
    target: ComponentIdentity,
    descriptor: CapabilityDescriptor,
    request: CapabilityRequest,
    consumer_component: ComponentIdentity,
    invoke_operation_id: str,
    invocation_ordinal: int,
    prefix_operations: tuple[OperationResult[JsonValue], ...],
) -> CapabilityEffectExecution:
    rows = list(prefix_operations)
    _, pending_operation = intent_operations.require_scope_clear(probe, request.context)
    rows.append(pending_operation)

    handle, prepare_handle_operation = provider.prepare_handle(
        session=session,
        target=target,
        request=request,
    )
    rows.append(prepare_handle_operation)
    intent = build_capability_effect_intent(request, target, invoke_operation_id, handle)

    _, pending_commit = intent_operations.require_scope_clear(intent, request.context)
    rows.append(pending_commit)
    _, journal_prepare = intent_operations.prepare(intent, request.context)
    rows.append(journal_prepare)

    execution = provider.execute_prepared(
        session=session,
        target=target,
        descriptor=descriptor,
        request=request,
        handle=handle,
        invocation_ordinal=invocation_ordinal,
    )
    rows.append(execution.operation)
    _, result_operation = intent_operations.record_result(
        intent,
        execution.result.effect,
        request.context,
    )
    rows.append(result_operation)

    result = execution.result
    disposition = capability_effect_disposition(result)
    if disposition is None:
        reconciliation, reconcile_operation = provider.reconcile(
            session=session,
            target=target,
            descriptor=descriptor,
            request=request,
            handle=handle,
        )
        rows.append(reconcile_operation)
        assert reconciliation.result is not None
        result = reconciliation.result
        disposition = reconciliation.disposition
        if disposition is not EffectReconciliationDisposition.NOT_APPLIED:
            _, reconciled_operation = intent_operations.record_reconciled(
                intent,
                result.effect,
                request.context,
            )
            rows.append(reconciled_operation)

    rows.extend(terminalize_capability_effect(
        intent_operations,
        intent=intent,
        result=result,
        disposition=disposition,
        consumer_component=consumer_component,
        completion_operation_id=execution.operation.operation_id,
        context=request.context,
    ))
    return CapabilityEffectExecution(result, tuple(rows), False)


__all__ = ["execute_new_capability_effect"]
