"""Crash-safe capability-effect execution.

One composition module owns capability effect validation, durable snapshots,
provider operations, recovery/new-flow transitions, and terminalization. The
durable truth remains the Effect Journal Authority and physical mutation remains
the capability Provider; this module is only their adjacent orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
    DurablePreparedCapabilitySession,
    capability_effect_request_id,
    capability_request_effect_class,
    capability_descriptor_minimum_execution_seconds,
    capability_request_minimum_execution_seconds,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    TaskDeadlineExceeded,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonValue,
    OperationResult,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
    thaw_json,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentPhase,
    EffectReconciliationDisposition,
    build_effect_intent,
    effect_completion,
    effect_result_snapshot,
    intent_field,
    prepared_handle_field,
    record_field,
    require_effect_receipt_request_digest,
    result_snapshot_field,
)
from noetrium_platform.research.execution.workflow.api import (
    EffectIntentOperationPort,
    OperationDispatchPort,
)

from .runtime import CapabilityInvocationExecution, CapabilityOperationAdapter


class UnsafeEffectfulCapability(RuntimeError):
    pass


class UnresolvedCapabilityEffect(RuntimeError):
    pass


class CapabilityEffectIdentityConflict(RuntimeError):
    pass


def capability_effect_intent(request: CapabilityRequest, target: ComponentIdentity, operation_id: str, recovery_handle: NoetriumUnit | None=None) -> NoetriumUnit:
    return build_effect_intent(request_id=capability_effect_request_id(request), request_digest=capability_request_digest(request), operation_id=operation_id, provider_component=target, context=request.context, recovery_handle=recovery_handle, intent_namespace='capability-effect-intent')


@dataclass(frozen=True, slots=True)
class CapabilityEffectExecution:
    result: CapabilityResult
    operation_results: tuple[OperationResult[JsonValue], ...]
    replayed_from_intent: bool = False


def require_durable_capability_session(session: object) -> DurablePreparedCapabilitySession:
    if not isinstance(session, DurablePreparedCapabilitySession):
        raise UnsafeEffectfulCapability('effectful capability provider must implement DurablePreparedCapabilitySession')
    if getattr(session, 'effect_recovery_durability', None) != 'crash_durable':
        raise UnsafeEffectfulCapability("effectful capability provider must declare effect_recovery_durability='crash_durable'")
    return session


def require_capability_effect_result(result: CapabilityResult, *, descriptor: CapabilityDescriptor, request: CapabilityRequest) -> CapabilityResult:
    if not isinstance(result, CapabilityResult):
        raise TypeError('effectful capability provider must return CapabilityResult')
    if result.capability_id != request.capability_id:
        raise CapabilityEffectIdentityConflict('capability result capability_id mismatch')
    if result.effect is None:
        raise CapabilityEffectIdentityConflict('effectful capability result must include EffectReceipt')
    try:
        require_effect_receipt_request_digest(result.effect, expected_digest=capability_request_digest(request), request_id=capability_effect_request_id(request), source='capability effect receipt')
    except ValueError as exc:
        raise CapabilityEffectIdentityConflict(str(exc)) from exc
    expected_class = capability_request_effect_class(descriptor, request)
    if result.effect.effect_class is not expected_class:
        raise CapabilityEffectIdentityConflict(f'capability effect class mismatch: declared={expected_class.value} actual={result.effect.effect_class.value}')
    return result


def require_capability_reconciliation(reconciliation: CapabilityEffectReconciliationResult, *, descriptor: CapabilityDescriptor, request: CapabilityRequest) -> CapabilityEffectReconciliationResult:
    if not isinstance(reconciliation, CapabilityEffectReconciliationResult):
        raise TypeError('reconcile_prepared_capability must return CapabilityEffectReconciliationResult')
    if reconciliation.capability_id != request.capability_id:
        raise CapabilityEffectIdentityConflict('capability reconciliation capability_id mismatch')
    if reconciliation.result is None:
        raise CapabilityEffectIdentityConflict('capability reconciliation requires provider CapabilityResult, including indeterminate outcomes')
    require_capability_effect_result(reconciliation.result, descriptor=descriptor, request=request)
    certainty = reconciliation.result.effect.certainty
    expected = {EffectReconciliationDisposition.APPLIED: {EffectCertainty.EFFECT_CONFIRMED}, EffectReconciliationDisposition.REJECTED: {EffectCertainty.EFFECT_REJECTED}, EffectReconciliationDisposition.NOT_APPLIED: {EffectCertainty.NO_EFFECT}, EffectReconciliationDisposition.UNKNOWN: {EffectCertainty.INDETERMINATE}}[reconciliation.disposition]
    if certainty not in expected:
        raise CapabilityEffectIdentityConflict(f'capability reconciliation proof mismatch: disposition={reconciliation.disposition.value} certainty={certainty.value}')
    return reconciliation


def capability_effect_disposition(result: CapabilityResult) -> EffectReconciliationDisposition:
    assert result.effect is not None
    try:
        return {EffectCertainty.EFFECT_CONFIRMED: EffectReconciliationDisposition.APPLIED, EffectCertainty.EFFECT_REJECTED: EffectReconciliationDisposition.REJECTED, EffectCertainty.NO_EFFECT: EffectReconciliationDisposition.NOT_APPLIED, EffectCertainty.INDETERMINATE: EffectReconciliationDisposition.UNKNOWN}[result.effect.certainty]
    except KeyError as exc:
        raise CapabilityEffectIdentityConflict(f'unsupported provider effect certainty: {result.effect.certainty}') from exc


_SCHEMA = 'noetrium.capability-result-snapshot.v1'


def _effect_document(effect: EffectReceipt | None) -> object:
    if effect is None:
        return None
    return {'effect_id': effect.effect_id, 'request_digest': effect.request_digest, 'effect_class': effect.effect_class.value, 'certainty': effect.certainty.value, 'provider_instance_id': effect.provider_instance_id, 'before_artifact': effect.before_artifact, 'after_artifact': effect.after_artifact, 'provider_receipt': effect.provider_receipt}


def _decode_effect(value: object) -> EffectReceipt | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError('capability result snapshot effect must be an object')
    return EffectReceipt(effect_id=str(value['effect_id']), request_digest=str(value['request_digest']), effect_class=EffectClass(str(value['effect_class'])), certainty=EffectCertainty(str(value['certainty'])), provider_instance_id=None if value.get('provider_instance_id') is None else str(value['provider_instance_id']), before_artifact=None if value.get('before_artifact') is None else str(value['before_artifact']), after_artifact=None if value.get('after_artifact') is None else str(value['after_artifact']), provider_receipt=None if value.get('provider_receipt') is None else str(value['provider_receipt']))


def _provider_document(identity: CapabilityProviderIdentity | None) -> object:
    if identity is None:
        return None
    return {'provider_id': identity.provider_id, 'implementation_version': identity.implementation_version, 'abi_version': identity.abi_version, 'schema_version': identity.schema_version, 'artifact_digest': identity.artifact_digest}


def _decode_provider(value: object) -> CapabilityProviderIdentity | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError('capability result snapshot provider identity must be an object')
    return CapabilityProviderIdentity(provider_id=str(value['provider_id']), implementation_version=str(value['implementation_version']), abi_version=str(value['abi_version']), schema_version=str(value['schema_version']), artifact_digest=str(value.get('artifact_digest') or ''))


def snapshot_capability_result(result: CapabilityResult) -> NoetriumUnit:
    if not isinstance(result, CapabilityResult):
        raise TypeError('capability result snapshot requires CapabilityResult')
    document = {'schema': _SCHEMA, 'capability_id': result.capability_id, 'payload': thaw_json(result.payload), 'generation': result.generation, 'artifacts': list(result.artifacts), 'diagnostics': thaw_json(result.diagnostics), 'effect': _effect_document(result.effect), 'provider_identity': _provider_document(result.provider_identity), 'request_digest': result.request_digest, 'evidence': thaw_json(result.evidence)}
    return effect_result_snapshot(schema=_SCHEMA, opaque_payload=canonical_bytes(document))


def restore_capability_result(snapshot: NoetriumUnit) -> CapabilityResult:
    schema = str(result_snapshot_field(snapshot, 'schema'))
    if schema != _SCHEMA:
        raise ValueError(f'unsupported capability result snapshot schema: {schema}')
    document = strict_json_loads(result_snapshot_field(snapshot, 'opaque_payload'))
    if not isinstance(document, Mapping) or document.get('schema') != _SCHEMA:
        raise ValueError('capability result snapshot document schema mismatch')
    raw_artifacts = document.get('artifacts', ())
    if not isinstance(raw_artifacts, list):
        raise ValueError('capability result snapshot artifacts must be an array')
    diagnostics = document.get('diagnostics', {})
    if not isinstance(diagnostics, Mapping):
        raise ValueError('capability result snapshot diagnostics must be an object')
    return CapabilityResult(capability_id=str(document['capability_id']), payload=document.get('payload'), generation=None if document.get('generation') is None else str(document['generation']), artifacts=tuple((str(value) for value in raw_artifacts)), diagnostics=dict(diagnostics), effect=_decode_effect(document.get('effect')), provider_identity=_decode_provider(document.get('provider_identity')), request_digest=None if document.get('request_digest') is None else str(document['request_digest']), evidence=document.get('evidence'))


class CapabilityEffectProviderOperations:
    """Provider-bound prepare/execute/reconcile operations; no WAL state authority."""

    def __init__(self, dispatcher: OperationDispatchPort, capability_operations: CapabilityOperationAdapter) -> None:
        self._dispatcher = dispatcher
        self._capability_operations = capability_operations

    @property
    def capability_operations(self) -> CapabilityOperationAdapter:
        return self._capability_operations

    def prepare_handle(self, *, session: DurablePreparedCapabilitySession, target: ComponentIdentity, request: CapabilityRequest, control: ExecutionControlPort) -> tuple[NoetriumUnit, OperationResult[JsonValue]]:
        dc = request.context.decision_cycle_id or request.context.span_id
        request_id = capability_effect_request_id(request)
        digest = capability_request_digest(request)
        operation = self._dispatcher.dispatch(root_context=request.context, operation_id=f'{dc}:capability.effect.prepare:{request_id}', operation_type='capability.effect.prepare', target=target, payload=request, payload_schema='capability.effect.prepare.v1', idempotency_key=request.idempotency_key, handler=lambda envelope: self._prepare_handle_payload(session, CapabilityRequest(envelope.payload.capability_id, envelope.payload.payload, envelope.context, envelope.payload.idempotency_key), request_id, digest, control), digest_output=False)
        return (self._dispatcher.require(operation), operation)

    @staticmethod
    def _prepare_handle_payload(session: DurablePreparedCapabilitySession, request: CapabilityRequest, request_id: str, request_digest: str, control: ExecutionControlPort) -> NoetriumUnit:
        control.checkpoint()
        handle = session.prepare_capability_effect(request, control)
        control.checkpoint()
        if type(handle) is not NoetriumUnit:
            raise TypeError('prepare_capability_effect must return effect.prepared-handle Unit')
        if prepared_handle_field(handle, 'request_id') != request_id or prepared_handle_field(handle, 'request_digest') != request_digest:
            raise CapabilityEffectIdentityConflict('prepared capability handle identity mismatch')
        return handle

    def execute_prepared(self, *, session: DurablePreparedCapabilitySession, target: ComponentIdentity, descriptor: CapabilityDescriptor, request: CapabilityRequest, handle: NoetriumUnit, control: ExecutionControlPort, invocation_ordinal: int) -> CapabilityInvocationExecution:
        return self._capability_operations.invoke(target=target, session=session, descriptor=descriptor, request=request, control=control, invocation_ordinal=invocation_ordinal, handler=lambda rebound, runtime_control: require_capability_effect_result(session.execute_prepared_capability(rebound, handle, runtime_control), descriptor=descriptor, request=rebound))

    def reconcile(self, *, session: DurablePreparedCapabilitySession, target: ComponentIdentity, descriptor: CapabilityDescriptor, request: CapabilityRequest, handle: NoetriumUnit, control: ExecutionControlPort, invocation_ordinal: int=0) -> tuple[CapabilityEffectReconciliationResult, OperationResult[JsonValue]]:
        dc = request.context.decision_cycle_id or request.context.span_id
        operation = self._dispatcher.dispatch(root_context=request.context, operation_id=f"{dc}:capability.effect.reconcile:{prepared_handle_field(handle, 'request_id')}:call:{invocation_ordinal}", operation_type='capability.effect.reconcile', target=target, payload=handle, payload_schema='capability.effect.reconcile.v1', idempotency_key=None if request.idempotency_key is None else f'{request.idempotency_key}:reconcile:{invocation_ordinal}', handler=lambda envelope: require_capability_reconciliation(session.reconcile_prepared_capability(handle, envelope.context, control), descriptor=descriptor, request=request), digest_output=False)
        return (self._dispatcher.require(operation), operation)


def terminalize_capability_effect(intent_operations: EffectIntentOperationPort, *, intent: NoetriumUnit, result: CapabilityResult, disposition: EffectReconciliationDisposition, consumer_component: ComponentIdentity, completion_operation_id: str, context: ExecutionContext) -> tuple[OperationResult[JsonValue], ...]:
    assert result.effect is not None
    if disposition is EffectReconciliationDisposition.NOT_APPLIED:
        intent_operations.record_not_applied(intent, result.effect)
        return ()
    if disposition is EffectReconciliationDisposition.UNKNOWN:
        intent_operations.record_indeterminate(intent, result.effect)
        return ()
    evidence = effect_completion(completion_key=str(intent_field(intent, 'request_id')), completion_operation_id=completion_operation_id, consumer_component_digest=canonical_digest(consumer_component), consumer_generation=context.generation('agent'))
    intent_operations.record_consumed(intent, evidence)
    return ()


def resolve_existing_capability_effect(*, intent_operations: EffectIntentOperationPort, provider: CapabilityEffectProviderOperations, existing: NoetriumUnit, probe: NoetriumUnit, session: DurablePreparedCapabilitySession, target: ComponentIdentity, descriptor: CapabilityDescriptor, request: CapabilityRequest, control: ExecutionControlPort, consumer_component: ComponentIdentity, completion_operation_id: str, invocation_ordinal: int, prefix_operations: tuple[OperationResult[JsonValue], ...]) -> CapabilityEffectExecution:
    existing_intent = record_field(existing, 'intent')
    if intent_field(existing_intent, 'request_digest') != intent_field(probe, 'request_digest'):
        raise CapabilityEffectIdentityConflict('same capability idempotency slot was reused with a different request digest')
    rows = list(prefix_operations)
    phase = record_field(existing, 'phase')
    if phase is not EffectIntentPhase.PREPARED:
        snapshot = record_field(existing, 'result_snapshot')
        if snapshot is None:
            raise UnresolvedCapabilityEffect('terminal/non-prepared capability effect predates durable result snapshots; provider reconfirmation is forbidden')
        result = require_capability_effect_result(restore_capability_result(snapshot), descriptor=descriptor, request=request)
        disposition = capability_effect_disposition(result)
        expected = {EffectIntentPhase.CONSUMED: {EffectReconciliationDisposition.APPLIED, EffectReconciliationDisposition.REJECTED}, EffectIntentPhase.NOT_APPLIED: {EffectReconciliationDisposition.NOT_APPLIED}, EffectIntentPhase.INDETERMINATE: {EffectReconciliationDisposition.UNKNOWN}}.get(phase)
        if expected is not None:
            if disposition not in expected:
                raise CapabilityEffectIdentityConflict(f'{phase.value} capability intent contradicts its durable result snapshot')
        else:
            rows.extend(terminalize_capability_effect(intent_operations, intent=existing_intent, result=result, disposition=disposition, consumer_component=consumer_component, completion_operation_id=completion_operation_id, context=request.context))
        return CapabilityEffectExecution(result, tuple(rows), True)
    recovery_handle = intent_field(existing_intent, 'recovery_handle')
    if recovery_handle is None:
        raise UnresolvedCapabilityEffect('prepared capability effect lacks durable recovery handle')
    reconciliation, operation = provider.reconcile(session=session, target=target, descriptor=descriptor, request=request, handle=recovery_handle, control=control, invocation_ordinal=invocation_ordinal)
    rows.append(operation)
    assert reconciliation.result is not None
    result = reconciliation.result
    disposition = reconciliation.disposition
    intent_operations.record_reconciled(
        existing_intent,
        result.effect,
        result_snapshot=snapshot_capability_result(result),
    )
    rows.extend(terminalize_capability_effect(intent_operations, intent=existing_intent, result=result, disposition=disposition, consumer_component=consumer_component, completion_operation_id=completion_operation_id, context=request.context))
    return CapabilityEffectExecution(result, tuple(rows), True)


def execute_new_capability_effect(*, intent_operations: EffectIntentOperationPort, provider: CapabilityEffectProviderOperations, probe: NoetriumUnit, session: DurablePreparedCapabilitySession, target: ComponentIdentity, descriptor: CapabilityDescriptor, request: CapabilityRequest, control: ExecutionControlPort, consumer_component: ComponentIdentity, invoke_operation_id: str, invocation_ordinal: int, prefix_operations: tuple[OperationResult[JsonValue], ...]) -> CapabilityEffectExecution:
    rows = list(prefix_operations)
    handle, prepare_handle_operation = provider.prepare_handle(session=session, target=target, request=request, control=control)
    rows.append(prepare_handle_operation)
    intent = capability_effect_intent(request, target, invoke_operation_id, handle)
    # Scope-clear proof and PREPARED insertion are one atomic Effect Journal
    # transaction. Separate preflight/commit checks were both slower and left a
    # TOCTOU window between proof and durable intent creation.
    intent_operations.prepare(intent)
    execution_error: BaseException | None = None
    try:
        execution = provider.execute_prepared(session=session, target=target, descriptor=descriptor, request=request, handle=handle, control=control, invocation_ordinal=invocation_ordinal)
    except BaseException as exc:
        execution_error = exc
        execution = None
    if execution is not None:
        rows.append(execution.operation)
        result = execution.result
        disposition = capability_effect_disposition(result)
        assert result.effect is not None
        consumption = (
            effect_completion(
                completion_key=str(intent_field(intent, "request_id")),
                completion_operation_id=invoke_operation_id,
                consumer_component_digest=canonical_digest(consumer_component),
                consumer_generation=request.context.generation("agent"),
            )
            if disposition
            in {
                EffectReconciliationDisposition.APPLIED,
                EffectReconciliationDisposition.REJECTED,
            }
            else None
        )
        intent_operations.record_terminal_result(
            intent,
            result.effect,
            result_snapshot=snapshot_capability_result(result),
            consumption=consumption,
        )
        return CapabilityEffectExecution(result, tuple(rows), False)
    result = None
    disposition = None
    if execution is None:
        try:
            reconciliation, reconcile_operation = provider.reconcile(session=session, target=target, descriptor=descriptor, request=request, handle=handle, control=control, invocation_ordinal=invocation_ordinal)
        except BaseException as reconcile_error:
            if execution_error is None:
                raise
            raise BaseExceptionGroup('prepared capability execution failed and effect reconciliation did not resolve', [execution_error, reconcile_error]) from execution_error
        rows.append(reconcile_operation)
        assert reconciliation.result is not None
        result = reconciliation.result
        disposition = reconciliation.disposition
        intent_operations.record_reconciled(
            intent,
            result.effect,
            result_snapshot=snapshot_capability_result(result),
        )
    assert result is not None
    assert disposition is not None
    rows.extend(terminalize_capability_effect(intent_operations, intent=intent, result=result, disposition=disposition, consumer_component=consumer_component, completion_operation_id=invoke_operation_id, context=request.context))
    return CapabilityEffectExecution(result, tuple(rows), False)


def _require_new_execution_budget(
    descriptor: CapabilityDescriptor,
    request: CapabilityRequest,
    control: ExecutionControlPort,
    *,
    pre_mediation: bool,
) -> None:
    control.checkpoint()
    minimum_seconds = (
        capability_descriptor_minimum_execution_seconds(descriptor)
        if pre_mediation
        else capability_request_minimum_execution_seconds(descriptor, request)
    )
    remaining_seconds = control.remaining_seconds
    if (
        minimum_seconds is not None
        and remaining_seconds is not None
        and remaining_seconds < minimum_seconds
    ):
        raise TaskDeadlineExceeded(
            "capability execution budget cannot contain provider minimum; "
            f"capability_id={request.capability_id}; "
            f"remaining_s={remaining_seconds:.6f}; "
            f"minimum_execution_s={minimum_seconds:.6f}"
        )


class CapabilityEffectExecutor:
    """Selects the crash-safe existing/new effect flow; phase semantics live in collaborators."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        effect_intents: EffectIntentOperationPort,
        capability_operations: CapabilityOperationAdapter,
    ) -> None:
        self._intent_operations = effect_intents
        self._provider = CapabilityEffectProviderOperations(
            dispatcher,
            capability_operations,
        )

    def preflight_new_execution(
        self,
        *,
        target: ComponentIdentity,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        control: ExecutionControlPort,
        invocation_ordinal: int = 0,
    ) -> None:
        """Fence a new effect before the capability RuntimeProgram is entered.

        Existing intent identity is payload-independent (stable idempotency slot,
        operation id and provider coordinate), so replay/reconciliation bypasses
        this fresh-execution fence even when PRE mediation rewrites payload later.
        The exact request-specific minimum is rechecked inside invoke().
        """
        if descriptor.effect_class not in {
            EffectClass.RECONCILABLE,
            EffectClass.NON_IDEMPOTENT,
        }:
            return
        if not isinstance(request.idempotency_key, str) or not request.idempotency_key.strip():
            raise UnsafeEffectfulCapability(
                "effectful capability invocation requires idempotency_key"
            )
        invoke_operation_id = self._provider.capability_operations.operation_id(
            request,
            invocation_ordinal=invocation_ordinal,
        )
        probe = capability_effect_intent(request, target, invoke_operation_id)
        if self._intent_operations.inspect(probe) is not None:
            return
        _require_new_execution_budget(
            descriptor,
            request,
            control,
            pre_mediation=True,
        )

    def invoke(self, *, target: ComponentIdentity, session: object, descriptor: CapabilityDescriptor, request: CapabilityRequest, control: ExecutionControlPort, consumer_component: ComponentIdentity, invocation_ordinal: int=0) -> CapabilityEffectExecution:
        if descriptor.effect_class not in {EffectClass.RECONCILABLE, EffectClass.NON_IDEMPOTENT}:
            raise ValueError('CapabilityEffectExecutor is only for reconciliable/non-idempotent capabilities')
        if not isinstance(request.idempotency_key, str) or not request.idempotency_key.strip():
            raise UnsafeEffectfulCapability('effectful capability invocation requires idempotency_key')
        durable = require_durable_capability_session(session)
        invoke_operation_id = self._provider.capability_operations.operation_id(request, invocation_ordinal=invocation_ordinal)
        probe = capability_effect_intent(request, target, invoke_operation_id)
        existing = self._intent_operations.inspect(probe)
        prefix = ()
        if existing is not None:
            return resolve_existing_capability_effect(intent_operations=self._intent_operations, provider=self._provider, existing=existing, probe=probe, session=durable, target=target, descriptor=descriptor, request=request, control=control, consumer_component=consumer_component, completion_operation_id=invoke_operation_id, invocation_ordinal=invocation_ordinal, prefix_operations=prefix)
        _require_new_execution_budget(
            descriptor,
            request,
            control,
            pre_mediation=False,
        )
        return execute_new_capability_effect(intent_operations=self._intent_operations, provider=self._provider, probe=probe, session=durable, target=target, descriptor=descriptor, request=request, control=control, consumer_component=consumer_component, invoke_operation_id=invoke_operation_id, invocation_ordinal=invocation_ordinal, prefix_operations=prefix)


__all__ = [
    "CapabilityEffectExecution",
    "CapabilityEffectExecutor",
    "CapabilityEffectIdentityConflict",
    "CapabilityEffectProviderOperations",
    "UnresolvedCapabilityEffect",
    "UnsafeEffectfulCapability",
    "capability_effect_disposition",
    "capability_effect_intent",
    "execute_new_capability_effect",
    "require_capability_effect_result",
    "require_capability_reconciliation",
    "require_durable_capability_session",
    "resolve_existing_capability_effect",
    "restore_capability_result",
    "snapshot_capability_result",
    "terminalize_capability_effect",
]
