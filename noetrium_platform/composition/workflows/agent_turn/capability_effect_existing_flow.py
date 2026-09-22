from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    DurablePreparedCapabilitySession,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntent,
    EffectIntentPhase,
    EffectIntentRecord,
    EffectReconciliationDisposition,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, JsonValue, OperationResult
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort

from .capability_effect_contracts import (
    CapabilityEffectExecution,
    CapabilityEffectIdentityConflict,
    UnresolvedCapabilityEffect,
)
from .capability_effect_provider import CapabilityEffectProviderOperations
from .capability_effect_terminal import terminalize_capability_effect


def resolve_existing_capability_effect(
    *,
    intent_operations: EffectIntentOperationPort,
    provider: CapabilityEffectProviderOperations,
    existing: EffectIntentRecord,
    probe: EffectIntent,
    session: DurablePreparedCapabilitySession,
    target: ComponentIdentity,
    descriptor: CapabilityDescriptor,
    request: CapabilityRequest,
    consumer_component: ComponentIdentity,
    completion_operation_id: str,
    prefix_operations: tuple[OperationResult[JsonValue], ...],
) -> CapabilityEffectExecution:
    if existing.intent.request_digest != probe.request_digest:
        raise CapabilityEffectIdentityConflict(
            "same capability idempotency slot was reused with a different request digest"
        )
    if existing.intent.recovery_handle is None:
        raise UnresolvedCapabilityEffect(
            "prepared capability effect lacks durable recovery handle"
        )

    rows = list(prefix_operations)
    reconciliation, operation = provider.reconcile(
        session=session,
        target=target,
        descriptor=descriptor,
        request=request,
        handle=existing.intent.recovery_handle,
    )
    rows.append(operation)
    assert reconciliation.result is not None
    disposition = reconciliation.disposition

    if existing.phase is EffectIntentPhase.CONSUMED:
        if disposition not in {
            EffectReconciliationDisposition.APPLIED,
            EffectReconciliationDisposition.REJECTED,
        }:
            raise CapabilityEffectIdentityConflict(
                "CONSUMED capability intent contradicts provider reconciliation"
            )
        return CapabilityEffectExecution(reconciliation.result, tuple(rows), True)

    if existing.phase is EffectIntentPhase.NOT_APPLIED:
        if disposition is not EffectReconciliationDisposition.NOT_APPLIED:
            raise CapabilityEffectIdentityConflict(
                "NOT_APPLIED capability intent contradicts provider reconciliation"
            )
        return CapabilityEffectExecution(reconciliation.result, tuple(rows), True)

    if disposition is not EffectReconciliationDisposition.NOT_APPLIED:
        _, reconciled_operation = intent_operations.record_reconciled(
            existing.intent,
            reconciliation.result.effect,
            request.context,
        )
        rows.append(reconciled_operation)

    rows.extend(terminalize_capability_effect(
        intent_operations,
        intent=existing.intent,
        result=reconciliation.result,
        disposition=disposition,
        consumer_component=consumer_component,
        completion_operation_id=completion_operation_id,
        context=request.context,
    ))
    return CapabilityEffectExecution(reconciliation.result, tuple(rows), True)


__all__ = ["resolve_existing_capability_effect"]
