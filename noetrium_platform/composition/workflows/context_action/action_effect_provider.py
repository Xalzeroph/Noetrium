from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRecoveryRequired,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    ActionSafetyCapabilityMissing,
    ActionSemanticIdentity,
    DurablePreparedActionSession,
    require_action_recovery_handle_identity,
    require_action_result_identity,
    require_recovery_handle_reconciliation_identity,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort

from .effect_safety import EffectSafetyPolicy


class ActionEffectProviderOperations:
    """Narrow authority for calls that can touch Environment effect state.

    This adapter owns no journal or workflow state.  Its only responsibility is to
    cross the Environment provider boundary through Kernel operations and verify the
    semantic identity of provider responses.
    """

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._environment_session = environment_session
        self._effect_policy = effect_policy

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    @staticmethod
    def _action_idempotency_key(request: ActionRequest) -> str:
        context = request.context
        return f"action:{context.run_id}:{context.decision_cycle_id or context.span_id}:{request.action_id}"

    def dispatch_act(
        self, request: ActionRequest, context: ExecutionContext
    ) -> tuple[ActionResult, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.act",
            operation_type="environment.act",
            target=self._bound.component("environment"),
            payload=request,
            payload_schema="environment.action.request.v1",
            idempotency_key=self._action_idempotency_key(request),
            handler=lambda envelope: require_action_result_identity(
                ActionRequest(
                    envelope.payload.action_id,
                    envelope.payload.action_type,
                    envelope.payload.payload,
                    envelope.context,
                ),
                self._environment_session.act(
                    ActionRequest(
                        envelope.payload.action_id,
                        envelope.payload.action_type,
                        envelope.payload.payload,
                        envelope.context,
                    )
                ),
                source="environment act",
            ),
            effect_projector=lambda output: (output.effect,) if output.effect is not None else (),
        )
        return self._dispatcher.require(operation), operation

    def dispatch_prepared_act(
        self,
        request: ActionRequest,
        handle: PreparedEffectHandle,
        context: ExecutionContext,
    ) -> tuple[ActionResult, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.act_prepared",
            operation_type="environment.act_prepared",
            target=self._bound.component("environment"),
            payload={"request": request, "recovery_handle": handle},
            payload_schema="environment.action.prepared_execution.v1",
            idempotency_key=self._action_idempotency_key(request),
            handler=lambda envelope: self._execute_prepared_action(
                envelope.payload["request"], envelope.payload["recovery_handle"]
            ),
            effect_projector=lambda output: (output.effect,) if output.effect is not None else (),
        )
        return self._dispatcher.require(operation), operation

    def _execute_prepared_action(
        self, request: ActionRequest, handle: PreparedEffectHandle
    ) -> ActionResult:
        if not isinstance(self._environment_session, DurablePreparedActionSession):
            raise ActionSafetyCapabilityMissing(
                "crash-durable prepared action execution requires durable Environment capability"
            )
        require_action_recovery_handle_identity(request, handle)
        return require_action_result_identity(
            request,
            self._environment_session.execute_prepared_action(request, handle),
            source="environment act",
        )

    def reconcile_effect(
        self,
        request: ActionRequest,
        result: ActionResult,
        context: ExecutionContext,
    ) -> tuple[ActionResult, OperationResult[JsonValue]]:
        if result.effect is None:
            raise ActionRecoveryRequired(
                "Environment action returned no EffectReceipt; effect reconciliation requires a receipt"
            )
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.reconcile",
            operation_type="environment.reconcile",
            target=self._bound.component("environment"),
            payload=result.effect,
            payload_schema="environment.effect.reconcile.request.v1",
            idempotency_key=f"action:{context.run_id}:{dc}:{request.action_id}:effect-reconcile",
            handler=lambda envelope: self._validate_reconciled_effect(
                request,
                self._effect_policy.require_resolved(
                    self._environment_session.reconcile(envelope.payload, envelope.context)
                ),
            ),
            effect_projector=lambda effect: (effect,),
        )
        reconciled = self._dispatcher.require(operation)
        return replace(result, effect=reconciled), operation

    @staticmethod
    def _validate_reconciled_effect(request: ActionRequest, effect):
        ActionSemanticIdentity.from_request(request).require_effect(
            effect, source="environment reconcile effect receipt"
        )
        return effect

    def reconcile_prepared_handle(
        self, handle: PreparedEffectHandle, context: ExecutionContext
    ) -> tuple[ActionReconciliationResult, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.reconcile_prepared_action",
            operation_type="environment.reconcile_prepared_action",
            target=self._bound.component("environment"),
            payload=handle,
            payload_schema="environment.action.reconcile_prepared_handle.v1",
            idempotency_key=f"action:{context.run_id}:{self._dc(context)}:{handle.request_id}",
            handler=lambda envelope: require_recovery_handle_reconciliation_identity(
                envelope.payload,
                self._call_reconcile_prepared_handle(envelope.payload, envelope.context),
            ),
            effect_projector=lambda output: (output.result.effect,)
            if output.result is not None and output.result.effect is not None
            else (),
        )
        return self._dispatcher.require(operation), operation

    def _call_reconcile_prepared_handle(
        self, handle: PreparedEffectHandle, context: ExecutionContext
    ) -> ActionReconciliationResult:
        if not isinstance(self._environment_session, DurablePreparedActionSession):
            raise ActionRecoveryRequired(
                f"prepared action {handle.request_id} cannot be reconciled: "
                "environment lacks durable recovery capability"
            )
        return self._environment_session.reconcile_prepared_action(handle, context)


__all__ = ["ActionEffectProviderOperations"]
