from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, PreparedEffectHandle
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRecoveryRequired,
    ActionRequest,
    ActionSemanticIdentity,
    require_action_recovery_handle_identity,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult, canonical_digest

from .action_contracts import ActionSafetyPermit, PreparedSafeAction
from .action_effect_identity import build_action_effect_intent
from .action_recovery_binding import ActionRecoveryRequestBinder
from noetrium_platform.research.execution.workflow.api import (
    EffectIntentOperationPort,
    OperationDispatchPort,
)
from noetrium_platform.capabilities.participant.core.api import BoundParticipants


class ActionAuthorizationBuilder:
    """Freezes one exact external-action authorization without executing the effect.

    It owns exact request construction, provider recovery-handle preparation, intent binding,
    and permit validation.  It owns no cross-call state and cannot invoke Environment ``act``.
    """

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        bound: BoundParticipants,
        environment_session: object,
        *,
        journal_ops: EffectIntentOperationPort | None,
        journal_durability: str | None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound = bound
        self._environment_session = environment_session
        self._journal_ops = journal_ops
        self._journal_durability = journal_durability
        self._recovery_binder = ActionRecoveryRequestBinder(dispatcher, bound)

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    @staticmethod
    def _action_idempotency_key(request: ActionRequest) -> str:
        context = request.context
        return f"action:{context.run_id}:{context.decision_cycle_id or context.span_id}:{request.action_id}"

    def _prepare_recovery_handle(
        self, request: ActionRequest, context: ExecutionContext
    ) -> tuple[PreparedEffectHandle, OperationResult[JsonValue]]:
        dc = self._dc(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:environment.action_recovery.prepare",
            operation_type="environment.action_recovery.prepare",
            target=self._bound.component("environment"),
            payload=request,
            payload_schema="environment.action_recovery.prepare.v1",
            idempotency_key=self._action_idempotency_key(request),
            handler=lambda envelope: require_action_recovery_handle_identity(
                envelope.payload,
                self._environment_session.prepare_action_recovery(
                    envelope.payload, envelope.context
                ),
            ),
        )
        return self._dispatcher.require(operation), operation

    def prepare(
        self,
        *,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
    ) -> PreparedSafeAction:
        dc = self._dc(context)
        request = ActionRequest(f"action_{dc}", action_type, action_payload, context)
        request, intent, rows = self._resolve_intent(
            request, action_type, action_payload, context
        )
        permit = self._permit_for(request, intent)
        return PreparedSafeAction(request, intent, permit, tuple(rows))

    def _resolve_intent(
        self,
        request: ActionRequest,
        action_type: str,
        action_payload: object,
        context: ExecutionContext,
    ) -> tuple[ActionRequest, EffectIntent | None, list[OperationResult[JsonValue]]]:
        if self._journal_ops is None:
            return request, None, []
        dc = self._dc(context)
        probe = build_action_effect_intent(
            request,
            operation_id=f"{dc}:environment.act",
            provider_component=self._bound.component("environment"),
        )
        existing, inspect_operation = self._journal_ops.inspect(probe, context, stage="commit")
        rows: list[OperationResult[JsonValue]] = [inspect_operation]
        if existing is not None:
            rebound, bind_operation = self._recovery_binder.bind(
                existing.intent,
                action_type=action_type,
                action_payload=action_payload,
                current_context=context,
            )
            request = rebound
            rows.append(bind_operation)
            intent = existing.intent
        else:
            intent = self._new_intent(request, context, rows)
        _, scope_operation = self._journal_ops.require_scope_clear(intent, context, stage="commit")
        rows.append(scope_operation)
        return request, intent, rows

    def _new_intent(
        self,
        request: ActionRequest,
        context: ExecutionContext,
        rows: list[OperationResult[JsonValue]],
    ) -> EffectIntent:
        dc = self._dc(context)
        recovery_handle, operation = self._prepare_recovery_handle(request, context)
        rows.append(operation)
        return build_action_effect_intent(
            request,
            operation_id=f"{dc}:environment.act",
            provider_component=self._bound.component("environment"),
            recovery_handle=recovery_handle,
        )

    def _permit_for(
        self, request: ActionRequest, intent: EffectIntent | None
    ) -> ActionSafetyPermit:
        return ActionSafetyPermit(
            self._dc(request.context),
            canonical_digest(self._bound.component("environment")),
            self._journal_durability,
            ActionSemanticIdentity.from_request(request).request_digest,
            intent.intent_id if intent is not None else None,
        )

    def require_prepared(self, prepared: PreparedSafeAction) -> None:
        request = prepared.request
        intent = prepared.intent
        expected = self._permit_for(request, intent)
        if prepared.permit != expected:
            raise ActionRecoveryRequired(
                "prepared action safety permit does not match frozen action/cycle/environment binding"
            )
        if intent is not None and intent.request_digest != expected.request_digest:
            raise ActionRecoveryRequired(
                "prepared action intent request digest does not match frozen action request"
            )


__all__ = ["ActionAuthorizationBuilder"]
