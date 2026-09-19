from __future__ import annotations

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.failure.api import OperationFailureReferenceProjection, exception_correlation_refs
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, ActionResult, action_request_digest
from noetrium_platform.foundation.kernel.kernel import OperationRequest


class StudyOperationFailureReferenceProjector:
    """Safe Study-specific causal projection; never emits provider opaque bytes.

    This adapter is deliberately outside Forensics Core.  It understands Study/Action
    contracts and projects only immutable identifiers/digests into generic references.
    """

    @staticmethod
    def _handle_refs(handle: PreparedEffectHandle) -> tuple[str, ...]:
        return (
            f"provider-recovery-schema:{handle.provider_schema}",
            f"provider-recovery-payload:{handle.payload_sha256}",
        )

    def project(
        self, request: OperationRequest[object], exc: BaseException
    ) -> OperationFailureReferenceProjection:
        payload = request.payload
        request_refs: list[str] = []
        effect_refs: list[str] = []
        correlations: list[str] = []

        def add_action(action: ActionRequest) -> None:
            request_refs.append(f"action-request:{action_request_digest(action)}")
            correlations.append(f"action:{action.action_id}")
            if action.context.checkpoint_id:
                correlations.append(f"checkpoint:{action.context.checkpoint_id}")

        def add_handle(handle: PreparedEffectHandle) -> None:
            request_refs.append(f"action-request:{handle.request_digest}")
            correlations.append(f"action:{handle.request_id}")
            correlations.extend(self._handle_refs(handle))

        if isinstance(payload, ActionRequest):
            add_action(payload)
        elif isinstance(payload, PreparedEffectHandle):
            add_handle(payload)
        elif isinstance(payload, EffectIntent):
            correlations.append(f"action-intent:{payload.intent_id}")
            request_refs.append(f"action-request:{payload.request_digest}")
            if payload.checkpoint_id:
                correlations.append(f"checkpoint:{payload.checkpoint_id}")
            if payload.recovery_handle is not None:
                correlations.extend(self._handle_refs(payload.recovery_handle))
        elif isinstance(payload, ActionResult):
            correlations.append(f"action:{payload.action_id}")
            if payload.effect is not None:
                effect_refs.append(payload.effect.effect_id)
                request_refs.append(f"action-request:{payload.effect.request_digest}")
        elif isinstance(payload, dict):
            embedded_request = payload.get("request")
            embedded_handle = payload.get("recovery_handle")
            embedded_intent = payload.get("intent")
            if isinstance(embedded_request, ActionRequest):
                add_action(embedded_request)
            if isinstance(embedded_handle, PreparedEffectHandle):
                add_handle(embedded_handle)
            if isinstance(embedded_intent, EffectIntent):
                correlations.append(f"action-intent:{embedded_intent.intent_id}")
                request_refs.append(f"action-request:{embedded_intent.request_digest}")
            intent_id = payload.get("intent_id")
            if isinstance(intent_id, str) and intent_id:
                correlations.append(f"action-intent:{intent_id}")
            completion = payload.get("consumption")
            completion_key = getattr(completion, "completion_key", None)
            if isinstance(completion_key, str) and completion_key:
                correlations.append(f"method-completion:{completion_key}")

        correlations.extend(exception_correlation_refs(exc))
        if request.idempotency_key:
            correlations.append(f"logical-operation:{request.idempotency_key}")
        return OperationFailureReferenceProjection(
            request_refs=tuple(dict.fromkeys(request_refs)),
            effect_refs=tuple(dict.fromkeys(effect_refs)),
            correlation_refs=tuple(dict.fromkeys(correlations)),
        )


__all__ = ["StudyOperationFailureReferenceProjector"]
