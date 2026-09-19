from __future__ import annotations

import base64
import json
from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionRequest,
    ActionResult,
    DurablePreparedActionSession,
    EnvironmentSession,
    Observation,
    require_action_recovery_handle_identity,
    require_action_result_identity,
    require_recovery_handle_reconciliation_identity,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonDocument,
    JsonInput,
    JsonValue,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectReconciliationDisposition,
    PreparedEffectHandle,
)

_REQUEST_SCHEMA = "noetrium.environment.action-capability.request.v1"
_RESULT_SCHEMA = "noetrium.environment.action-capability.result.v1"
_HANDLE_SCHEMA = "noetrium.environment.action-capability.handle.v1"


def environment_action_capability_payload(action_type: str, payload: JsonInput) -> dict[str, JsonInput]:
    """Build the provider-neutral payload consumed by the environment action bridge."""
    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("environment capability action_type must be non-empty")
    return {"action_type": action_type, "payload": payload}


def _jsonable(value: JsonValue) -> JsonInput:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise TypeError(f"environment capability handle cannot encode {type(value).__qualname__}")


def _observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment capability observation must be Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


def _effect_lineage(effect: EffectReceipt | None) -> dict[str, JsonValue]:
    if effect is None:
        return {}
    return {
        "effect_id": effect.effect_id,
        "request_digest": effect.request_digest,
        "effect_class": effect.effect_class.value,
        "certainty": effect.certainty.value,
        "provider_instance_id": effect.provider_instance_id,
        "verification_required": effect.verification_required,
        "before_artifact": effect.before_artifact,
        "after_artifact": effect.after_artifact,
        "provider_receipt": effect.provider_receipt,
    }


def _inner_handle_document(handle: PreparedEffectHandle) -> dict[str, JsonInput]:
    return {
        "request_id": handle.request_id,
        "request_digest": handle.request_digest,
        "provider_schema": handle.provider_schema,
        "opaque_payload_b64": base64.b64encode(handle.opaque_payload).decode("ascii"),
        "payload_sha256": handle.payload_sha256,
        "provider_instance_id": handle.provider_instance_id,
    }


def _inner_handle(document: JsonDocument) -> PreparedEffectHandle:
    return PreparedEffectHandle(
        request_id=str(document["request_id"]),
        request_digest=str(document["request_digest"]),
        provider_schema=str(document["provider_schema"]),
        opaque_payload=base64.b64decode(str(document["opaque_payload_b64"]).encode("ascii")),
        payload_sha256=str(document["payload_sha256"]),
        provider_instance_id=(
            None if document.get("provider_instance_id") is None else str(document["provider_instance_id"])
        ),
    )


def _encode_wrapper(handle: PreparedEffectHandle, request: CapabilityRequest) -> bytes:
    document: dict[str, JsonInput] = {
        "inner_handle": _inner_handle_document(handle),
        "capability_request": {
            "capability_id": request.capability_id,
            "payload": _jsonable(request.payload),
            "idempotency_key": request.idempotency_key,
        },
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_wrapper(
    payload: bytes,
    context: ExecutionContext,
) -> tuple[PreparedEffectHandle, CapabilityRequest]:
    raw = json.loads(payload.decode("utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("environment capability handle payload must be an object")
    inner_doc = raw.get("inner_handle")
    request_doc = raw.get("capability_request")
    if not isinstance(inner_doc, dict) or not isinstance(request_doc, dict):
        raise TypeError("environment capability handle is missing typed wrapper fields")
    inner = _inner_handle(inner_doc)
    request = CapabilityRequest(
        capability_id=str(request_doc["capability_id"]),
        payload=request_doc.get("payload"),
        context=context,
        idempotency_key=(
            None if request_doc.get("idempotency_key") is None else str(request_doc["idempotency_key"])
        ),
    )
    return inner, request


class EnvironmentSessionCapabilityAdapter:
    """Mechanical EnvironmentSession -> capability-provider adapter.

    It owns no effect truth. The generic capability effect layer owns the outer
    intent/recovery lifecycle; the wrapped EnvironmentSession owns provider action
    recovery. This adapter translates identities between the two public protocols and
    preserves the inner environment receipt as provider lineage.
    """

    def __init__(
        self,
        session: EnvironmentSession,
        *,
        capability_id: str = "environment.act",
        effect_class: EffectClass = EffectClass.RECONCILABLE,
    ) -> None:
        if not isinstance(session, EnvironmentSession):
            raise TypeError("environment capability bridge requires EnvironmentSession")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("environment capability id must be non-empty")
        if not isinstance(effect_class, EffectClass):
            raise TypeError("environment capability effect_class must be EffectClass")
        self._session = session
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=effect_class,
            deterministic=False,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    @property
    def effect_recovery_durability(self) -> str:
        durability = getattr(self._session, "action_recovery_durability", "process_local")
        return "crash_durable" if durability == "crash_durable" else "process_local"

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        self._require_capability_id(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if self._descriptor.effect_class not in {EffectClass.PURE, EffectClass.IDEMPOTENT}:
            raise RuntimeError(
                "effectful environment capability must be routed through CapabilityEffectExecutor"
            )
        action = self._action_request(request)
        result = require_action_result_identity(
            action,
            self._session.act(action),
            source="environment capability direct action",
        )
        return self._capability_result(request, result)

    def prepare_capability_effect(self, request: CapabilityRequest) -> PreparedEffectHandle:
        session = self._durable_session()
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(
            action,
            session.prepare_action_recovery(action, request.context),
        )
        return PreparedEffectHandle.build(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema=_HANDLE_SCHEMA,
            opaque_payload=_encode_wrapper(inner, request),
            provider_instance_id=inner.provider_instance_id,
        )

    def execute_prepared_capability(
        self,
        request: CapabilityRequest,
        handle: PreparedEffectHandle,
    ) -> CapabilityResult:
        self._require_outer_handle(request, handle)
        session = self._durable_session()
        inner, stored_request = _decode_wrapper(handle.opaque_payload, request.context)
        if capability_request_digest(stored_request) != capability_request_digest(request):
            raise ValueError("environment capability prepared request drift")
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(action, inner)
        result = require_action_result_identity(
            action,
            session.execute_prepared_action(action, inner),
            source="environment capability prepared action",
        )
        return self._capability_result(request, result)

    def reconcile_prepared_capability(
        self,
        handle: PreparedEffectHandle,
        context: ExecutionContext,
    ) -> CapabilityEffectReconciliationResult:
        if not isinstance(handle, PreparedEffectHandle):
            raise TypeError("environment capability reconciliation requires PreparedEffectHandle")
        if handle.provider_schema != _HANDLE_SCHEMA:
            raise ValueError("environment capability prepared handle schema mismatch")
        session = self._durable_session()
        inner, request = _decode_wrapper(handle.opaque_payload, context)
        self._require_outer_handle(request, handle)
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(action, inner)
        reconciliation = require_recovery_handle_reconciliation_identity(
            inner,
            session.reconcile_prepared_action(inner, context),
        )
        result = None if reconciliation.result is None else self._capability_result(request, reconciliation.result)
        disposition = {
            ActionReconciliationDisposition.APPLIED: EffectReconciliationDisposition.APPLIED,
            ActionReconciliationDisposition.REJECTED: EffectReconciliationDisposition.REJECTED,
            ActionReconciliationDisposition.NOT_APPLIED: EffectReconciliationDisposition.NOT_APPLIED,
            ActionReconciliationDisposition.UNKNOWN: EffectReconciliationDisposition.UNKNOWN,
        }[reconciliation.disposition]
        return CapabilityEffectReconciliationResult(
            capability_id=self._descriptor.capability_id,
            disposition=disposition,
            result=result,
            diagnostics={"environment_reconciliation": dict(reconciliation.diagnostics)},
        )

    def checkpoint(self) -> bytes:
        return self._session.checkpoint()

    def restore(self, payload: bytes) -> None:
        self._session.restore(payload)

    def close(self) -> None:
        self._session.close()

    def _durable_session(self) -> DurablePreparedActionSession:
        if not isinstance(self._session, DurablePreparedActionSession):
            raise RuntimeError("effectful environment capability requires DurablePreparedActionSession")
        if self.effect_recovery_durability != "crash_durable":
            raise RuntimeError("effectful environment capability requires crash-durable action recovery")
        return self._session

    def _require_capability_id(self, capability_id: str) -> None:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)

    def _payload(self, request: CapabilityRequest) -> tuple[str, JsonInput]:
        self._require_capability_id(request.capability_id)
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("environment capability payload must be a mapping")
        action_type = payload.get("action_type")
        if not isinstance(action_type, str) or not action_type.strip():
            raise ValueError("environment capability payload requires action_type")
        if "payload" not in payload:
            raise ValueError("environment capability payload requires payload")
        return action_type, payload["payload"]

    def _action_request(self, request: CapabilityRequest) -> ActionRequest:
        action_type, action_payload = self._payload(request)
        return ActionRequest(
            action_id=capability_effect_request_id(request),
            action_type=action_type,
            payload=action_payload,
            context=request.context,
        )

    def _outer_effect(self, request: CapabilityRequest, effect: EffectReceipt | None) -> EffectReceipt | None:
        if effect is None:
            return None
        if effect.effect_class is not self._descriptor.effect_class:
            raise ValueError("environment action effect class does not match exported capability descriptor")
        return EffectReceipt(
            effect_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            effect_class=self._descriptor.effect_class,
            certainty=effect.certainty,
            provider_instance_id=effect.provider_instance_id,
            verification_required=effect.verification_required,
            before_artifact=effect.before_artifact,
            after_artifact=effect.after_artifact,
            provider_receipt=effect.provider_receipt or effect.effect_id,
        )

    def _capability_result(self, request: CapabilityRequest, result: ActionResult) -> CapabilityResult:
        observation = result.observation
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={"accepted": result.accepted, "observation": _observation_payload(observation)},
            generation=None if observation is None else observation.generation,
            artifacts=() if observation is None else observation.artifact_refs,
            diagnostics={
                "accepted": result.accepted,
                "environment_action_id": result.action_id,
                "environment_diagnostics": dict(result.diagnostics),
                "environment_effect": _effect_lineage(result.effect),
            },
            effect=self._outer_effect(request, result.effect),
            request_digest=capability_request_digest(request),
        )

    def _require_outer_handle(self, request: CapabilityRequest, handle: PreparedEffectHandle) -> None:
        if not isinstance(handle, PreparedEffectHandle):
            raise TypeError("environment capability prepared execution requires PreparedEffectHandle")
        if handle.request_id != capability_effect_request_id(request):
            raise ValueError("environment capability prepared handle request id mismatch")
        if handle.request_digest != capability_request_digest(request):
            raise ValueError("environment capability prepared handle request digest mismatch")
        if handle.provider_schema != _HANDLE_SCHEMA:
            raise ValueError("environment capability prepared handle schema mismatch")


__all__ = ["EnvironmentSessionCapabilityAdapter", "environment_action_capability_payload"]
