from __future__ import annotations

import base64
import json
from hashlib import sha256
from collections.abc import Mapping
import math

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    EnvironmentBranchStatePort,
    EnvironmentCapability,
    EnvironmentCapabilityUnsupported,
    EnvironmentConformanceProbe,
    EnvironmentDiagnosticsPort,
    EnvironmentIdentity,
    EnvironmentProviderCapabilities,
    EnvironmentProviderConformanceReceipt,
    EnvironmentProviderPort,
    EnvironmentRecoverySession,
    EnvironmentResetPort,
    EnvironmentSessionDiagnostics,
    EnvironmentSessionServices,
    require_environment_provider_identity,
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
    capability_request_effect_class,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort, UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonDocument,
    JsonInput,
    JsonValue,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectReconciliationDisposition,
    is_prepared_effect_handle,
    prepared_effect_handle,
    prepared_handle_field,
)

from .observation import (
    observation_evidence,
    raw_observation_payload,
    semantic_observation_payload,
)

_REQUEST_SCHEMA = "noetrium.environment.action-capability.request.v1"
_RESULT_SCHEMA = "noetrium.environment.action-capability.result.v1"
_HANDLE_SCHEMA = "noetrium.environment.action-capability.handle.v1"


def environment_capability_descriptor_metadata(descriptors) -> dict[str, JsonValue]:
    rows = tuple(descriptors)
    # Derived, never hand-maintained: current EnvironmentSession catalogs are
    # the only source of authorized action truth and physical mutability.
    actions: dict[str, str] = {}
    action_minimum_seconds: dict[str, float] = {}
    for descriptor in rows:
        raw_minimum = descriptor.metadata.get("minimum_action_execution_seconds")
        if raw_minimum is not None:
            if isinstance(raw_minimum, bool) or not isinstance(raw_minimum, (int, float)):
                raise TypeError("environment minimum_action_execution_seconds must be numeric")
            minimum = float(raw_minimum)
            if not math.isfinite(minimum) or minimum <= 0.0:
                raise ValueError("environment minimum_action_execution_seconds must be finite and positive")
            for action_type in descriptor.action_types:
                previous = action_minimum_seconds.get(action_type)
                if previous is not None and previous != minimum:
                    raise ValueError("conflicting environment action execution minimum: " + action_type)
                action_minimum_seconds[action_type] = minimum
        reference = descriptor.metadata.get("action_contracts", ())
        for contract in reference:
            if not isinstance(contract, Mapping):
                raise TypeError("environment action contract must be a mapping")
            name = contract.get("action_type")
            mutates = contract.get("mutates_world")
            if not isinstance(name, str) or type(mutates) is not bool:
                raise TypeError("environment action contract requires typed mutates_world")
            effect = (
                EffectClass.RECONCILABLE.value if mutates else EffectClass.PURE.value
            )
            if name in actions and actions[name] != effect:
                raise ValueError("conflicting environment action effect class: " + name)
            actions[name] = effect
    result: dict[str, JsonValue] = {
        "environment_capabilities": tuple(
            {
                "capability_id": descriptor.capability_id,
                "version": descriptor.version,
                "action_types": descriptor.action_types,
                "query_types": descriptor.query_types,
                "metadata": descriptor.metadata,
            }
            for descriptor in rows
        )
    }
    if actions:
        result["action_effect_classes"] = actions
    if action_minimum_seconds:
        result["action_minimum_execution_seconds"] = action_minimum_seconds
        # PRE capability mediation may rewrite the action payload. The generic
        # router therefore needs one request-independent preflight bound before
        # entering the RuntimeProgram; the exact per-action value is rechecked
        # after mediation. max() is conservative and provider-derived.
        result["minimum_execution_seconds"] = max(action_minimum_seconds.values())
    return result

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


def _effect_lineage(effect: EffectReceipt | None) -> dict[str, JsonValue]:
    if effect is None:
        return {}
    return {
        "effect_id": effect.effect_id,
        "request_digest": effect.request_digest,
        "effect_class": effect.effect_class.value,
        "certainty": effect.certainty.value,
        "provider_instance_id": effect.provider_instance_id,
        "before_artifact": effect.before_artifact,
        "after_artifact": effect.after_artifact,
        "provider_receipt": effect.provider_receipt,
    }


def _inner_handle_document(handle: NoetriumUnit) -> dict[str, JsonInput]:
    return {
        "request_id": prepared_handle_field(handle, "request_id"),
        "request_digest": prepared_handle_field(handle, "request_digest"),
        "provider_schema": prepared_handle_field(handle, "provider_schema"),
        "opaque_payload_b64": base64.b64encode(
            prepared_handle_field(handle, "opaque_payload")
        ).decode("ascii"),
        "payload_sha256": prepared_handle_field(handle, "payload_sha256"),
        "provider_instance_id": prepared_handle_field(handle, "provider_instance_id"),
    }


def _inner_handle(document: JsonDocument) -> NoetriumUnit:
    handle = prepared_effect_handle(
        request_id=str(document["request_id"]),
        request_digest=str(document["request_digest"]),
        provider_schema=str(document["provider_schema"]),
        opaque_payload=base64.b64decode(str(document["opaque_payload_b64"]).encode("ascii")),
        provider_instance_id=(
            None if document.get("provider_instance_id") is None else str(document["provider_instance_id"])
        ),
    )
    if prepared_handle_field(handle, "payload_sha256") != str(document["payload_sha256"]):
        raise ValueError("environment capability inner handle checksum mismatch")
    return handle


def _encode_wrapper(handle: NoetriumUnit, request: CapabilityRequest) -> bytes:
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
) -> tuple[NoetriumUnit, CapabilityRequest]:
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


class EnvironmentCapabilityProvider:
    """Generic capability provider over an EnvironmentSession.

    It owns no effect truth. The generic capability effect layer owns the outer
    intent/recovery lifecycle; the wrapped EnvironmentSession owns provider action
    recovery. This provider projects identities between the two public protocols and
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
        describe_environment = getattr(session, "capability_descriptors", None)
        descriptors = () if not callable(describe_environment) else tuple(describe_environment())
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=effect_class,
            deterministic=False,
            metadata=environment_capability_descriptor_metadata(descriptors),
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

    def invoke(self, request: CapabilityRequest, control: ExecutionControlPort) -> CapabilityResult:
        if self._descriptor.effect_class not in {EffectClass.PURE, EffectClass.IDEMPOTENT}:
            raise RuntimeError(
                "effectful environment capability must be routed through CapabilityEffectExecutor"
            )
        action = self._action_request(request)
        result = require_action_result_identity(
            action,
            self._session.act(action, control),
            source="environment capability direct action",
        )
        return self._capability_result(request, result)

    def prepare_capability_effect(
        self,
        request: CapabilityRequest,
        control: ExecutionControlPort,
    ) -> NoetriumUnit:
        session = self._durable_session()
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(
            action,
            session.prepare_action_recovery(action, request.context, control),
        )
        return prepared_effect_handle(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema=_HANDLE_SCHEMA,
            opaque_payload=_encode_wrapper(inner, request),
            provider_instance_id=prepared_handle_field(inner, "provider_instance_id"),
        )

    def execute_prepared_capability(
        self,
        request: CapabilityRequest,
        handle: NoetriumUnit,
        control: ExecutionControlPort,
    ) -> CapabilityResult:
        self._require_outer_handle(request, handle)
        session = self._durable_session()
        inner, stored_request = _decode_wrapper(prepared_handle_field(handle, "opaque_payload"), request.context)
        if capability_request_digest(stored_request) != capability_request_digest(request):
            raise ValueError("environment capability prepared request drift")
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(action, inner)
        result = require_action_result_identity(
            action,
            session.execute_prepared_action(action, inner, control),
            source="environment capability prepared action",
        )
        return self._capability_result(request, result)

    def reconcile_prepared_capability(
        self,
        handle: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> CapabilityEffectReconciliationResult:
        if type(handle) is not NoetriumUnit:
            raise TypeError("environment capability reconciliation requires NoetriumUnit")
        if prepared_handle_field(handle, "provider_schema") != _HANDLE_SCHEMA:
            raise ValueError("environment capability prepared handle schema mismatch")
        session = self._durable_session()
        inner, request = _decode_wrapper(prepared_handle_field(handle, "opaque_payload"), context)
        self._require_outer_handle(request, handle)
        action = self._action_request(request)
        inner = require_action_recovery_handle_identity(action, inner)
        reconciliation = require_recovery_handle_reconciliation_identity(
            inner,
            session.reconcile_prepared_action(inner, context, control),
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
        declared = capability_request_effect_class(self._descriptor, request)
        if effect.effect_class is not declared:
            raise ValueError("environment action effect class does not match exported capability descriptor")
        return EffectReceipt(
            effect_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            effect_class=declared,
            certainty=effect.certainty,
            provider_instance_id=effect.provider_instance_id,
            before_artifact=effect.before_artifact,
            after_artifact=effect.after_artifact,
            provider_receipt=effect.provider_receipt or effect.effect_id,
        )

    def _capability_result(self, request: CapabilityRequest, result: ActionResult) -> CapabilityResult:
        observation = result.observation
        raw_observation = raw_observation_payload(observation)
        semantic_observation = semantic_observation_payload(observation)
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={"accepted": result.accepted, "observation": semantic_observation},
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
            evidence=(
                None
                if raw_observation is None
                else {
                    "schema": "noetrium.environment.action-evidence.v2",
                    "observation": raw_observation,
                    # Research/evaluator evidence only. This is carried in the
                    # sealed Method event stream and is deliberately absent from
                    # the semantic observation shown to the Agent.
                    "environment_diagnostics": dict(result.diagnostics),
                }
            ),
        )

    def _require_outer_handle(self, request: CapabilityRequest, handle: NoetriumUnit) -> None:
        if type(handle) is not NoetriumUnit:
            raise TypeError("environment capability prepared execution requires NoetriumUnit")
        if prepared_handle_field(handle, "request_id") != capability_effect_request_id(request):
            raise ValueError("environment capability prepared handle request id mismatch")
        if prepared_handle_field(handle, "request_digest") != capability_request_digest(request):
            raise ValueError("environment capability prepared handle request digest mismatch")
        if prepared_handle_field(handle, "provider_schema") != _HANDLE_SCHEMA:
            raise ValueError("environment capability prepared handle schema mismatch")


__all__ = ["EnvironmentCapabilityProvider", "environment_action_capability_payload"]


def verify_environment_provider_conformance(
    provider: EnvironmentProviderPort,
    *,
    probe: EnvironmentConformanceProbe,
    services: EnvironmentSessionServices,
) -> EnvironmentProviderConformanceReceipt:
    """Exercise only the public provider/session seam and fail closed on identity drift."""

    if not isinstance(provider, EnvironmentProviderPort):
        raise TypeError("provider does not satisfy EnvironmentProviderPort")
    identity = provider.identity
    if not isinstance(identity, EnvironmentIdentity):
        raise TypeError("environment provider exposes the wrong identity type")
    require_environment_provider_identity(identity)
    capabilities = provider.capabilities
    if not isinstance(capabilities, EnvironmentProviderCapabilities):
        raise TypeError("environment provider exposes untyped capabilities")

    session = provider.open_session(session_id=probe.session_id, services=services)
    if not isinstance(session, EnvironmentSession):
        raise TypeError("provider returned a session outside EnvironmentSession")

    checks: list[str] = ["provider_identity", "open_session"]
    snapshot_digest: str | None = None
    action_id: str | None = None
    diagnostics_generation: str | None = None
    try:
        observation = session.observe(probe.context)
        if not isinstance(observation, Observation):
            raise TypeError("environment session observe() returned the wrong type")
        if not observation.observation_id.strip() or not observation.generation.strip():
            raise ValueError("environment observation identity is incomplete")
        checks.append("observe")

        if capabilities.supports(EnvironmentCapability.BRANCH_STATE):
            if not isinstance(session, EnvironmentBranchStatePort):
                raise TypeError("branch-state capability lacks EnvironmentBranchStatePort")
            checks.append("branch_state_port")

        if capabilities.supports(EnvironmentCapability.RESET):
            if not isinstance(session, EnvironmentResetPort):
                raise TypeError("reset capability lacks EnvironmentResetPort")
            observation = session.reset(probe.context)
            if not isinstance(observation, Observation):
                raise TypeError("environment reset returned the wrong type")
            if not observation.observation_id.strip() or not observation.generation.strip():
                raise ValueError("environment reset observation identity is incomplete")
            checks.append("reset")

        payload: bytes | None = None
        if capabilities.supports(EnvironmentCapability.SNAPSHOT):
            if not isinstance(session, EnvironmentRecoverySession):
                raise TypeError("snapshot capability lacks EnvironmentRecoverySession")
            payload = session.checkpoint()
            if not isinstance(payload, bytes) or not payload:
                raise TypeError("environment snapshot must be non-empty bytes")
            snapshot_digest = sha256(payload).hexdigest()
            checks.append("snapshot")
        else:
            try:
                session.checkpoint()
            except EnvironmentCapabilityUnsupported as exc:
                if exc.capability != EnvironmentCapability.SNAPSHOT.value:
                    raise ValueError("snapshot unsupported capability identity drift") from exc
            else:
                raise ValueError("snapshot behavior contradicts provider capabilities")
            checks.append("snapshot_unsupported")

        if capabilities.supports(EnvironmentCapability.RESTORE):
            if not isinstance(session, EnvironmentRecoverySession):
                raise TypeError("restore capability lacks EnvironmentRecoverySession")
            if payload is None:
                raise ValueError("restore capability requires an available snapshot")
            session.restore(payload)
            checks.append("restore")
        else:
            try:
                session.restore(payload or b"")
            except EnvironmentCapabilityUnsupported as exc:
                if exc.capability != EnvironmentCapability.RESTORE.value:
                    raise ValueError("restore unsupported capability identity drift") from exc
            else:
                raise ValueError("restore behavior contradicts provider capabilities")
            checks.append("restore_unsupported")

        if probe.action is not None:
            result = session.act(probe.action, UNBOUNDED_EXECUTION_CONTROL)
            if not isinstance(result, ActionResult) or result.action_id != probe.action.action_id:
                raise TypeError("environment session returned an invalid action result")
            action_id = result.action_id
            checks.append("act")
            if capabilities.supports(EnvironmentCapability.RECONCILE):
                if not isinstance(result.effect, EffectReceipt):
                    raise TypeError("reconcilable environment action must return EffectReceipt")
                reconciled = session.reconcile(result.effect, probe.context)
                if not isinstance(reconciled, EffectReceipt):
                    raise TypeError("environment reconcile() returned the wrong type")
                if reconciled.request_digest != result.effect.request_digest:
                    raise ValueError("environment reconciliation changed request identity")
                checks.append("reconcile")
            elif isinstance(result.effect, EffectReceipt):
                try:
                    session.reconcile(result.effect, probe.context)
                except EnvironmentCapabilityUnsupported as exc:
                    if exc.capability != EnvironmentCapability.RECONCILE.value:
                        raise ValueError("reconcile unsupported capability identity drift") from exc
                else:
                    raise ValueError("reconcile behavior contradicts provider capabilities")
                checks.append("reconcile_unsupported")

        if capabilities.supports(EnvironmentCapability.DIAGNOSTICS):
            if not isinstance(session, EnvironmentDiagnosticsPort):
                raise TypeError("diagnostics capability lacks EnvironmentDiagnosticsPort")
            diagnostics = session.diagnostics_snapshot()
            if not isinstance(diagnostics, EnvironmentSessionDiagnostics):
                raise TypeError("environment diagnostics returned the wrong type")
            if diagnostics.session_id != probe.session_id or diagnostics.environment != identity:
                raise ValueError("environment diagnostics identity drift")
            if diagnostics.generation != observation.generation:
                raise ValueError("environment diagnostics generation drift")
            if diagnostics.closed or not diagnostics.ready:
                raise ValueError("newly opened environment session is not ready")
            diagnostics_generation = diagnostics.generation
            checks.append("diagnostics")
    finally:
        session.close()

    return EnvironmentProviderConformanceReceipt(
        environment=identity,
        capabilities=capabilities,
        session_id=probe.session_id,
        observation_id=observation.observation_id,
        observation_generation=observation.generation,
        checks=tuple(checks),
        snapshot_sha256=snapshot_digest,
        action_id=action_id,
        diagnostics_generation=diagnostics_generation,
    )

