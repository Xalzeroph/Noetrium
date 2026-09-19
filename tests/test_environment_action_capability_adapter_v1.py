from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    Observation,
    action_request_digest,
)
from noetrium_platform.capabilities.environment.composition import (
    EnvironmentSessionCapabilityAdapter,
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityRequest,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
)
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        study_id="study-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


def _result(request: ActionRequest) -> ActionResult:
    effect = EffectReceipt(
        effect_id="environment-effect-1",
        request_digest=action_request_digest(request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.EFFECT_CONFIRMED,
        provider_instance_id="environment-provider-1",
        provider_receipt="environment-receipt-1",
    )
    return ActionResult(
        action_id=request.action_id,
        accepted=True,
        observation=Observation("obs-2", "env-gen-2", {"text": "done"}, ("artifact-1",)),
        effect=effect,
        diagnostics={"won": True},
    )


class _DurableEnvironment:
    action_recovery_durability = "crash_durable"

    def __init__(self) -> None:
        self.prepared_request: ActionRequest | None = None
        self.closed = False

    def observe(self, context: ExecutionContext) -> Observation:
        del context
        return Observation("obs-1", "env-gen-1", {"text": "start"})

    def act(self, request: ActionRequest) -> ActionResult:
        return _result(request)

    def reconcile(self, effect: EffectReceipt, context: ExecutionContext) -> EffectReceipt:
        del context
        return effect

    def prepare_action_recovery(
        self,
        request: ActionRequest,
        context: ExecutionContext,
    ) -> PreparedEffectHandle:
        del context
        self.prepared_request = request
        return PreparedEffectHandle.build(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema="fake-environment-action.v1",
            opaque_payload=b"prepared-environment-action",
            provider_instance_id="environment-provider-1",
        )

    def execute_prepared_action(
        self,
        request: ActionRequest,
        handle: PreparedEffectHandle,
    ) -> ActionResult:
        assert self.prepared_request is not None
        assert handle.request_id == request.action_id
        assert handle.request_digest == action_request_digest(request)
        return _result(request)

    def reconcile_prepared_action(
        self,
        handle: PreparedEffectHandle,
        context: ExecutionContext,
    ) -> ActionReconciliationResult:
        del context
        assert self.prepared_request is not None
        assert handle.request_id == self.prepared_request.action_id
        return ActionReconciliationResult(
            action_id=handle.request_id,
            disposition=ActionReconciliationDisposition.APPLIED,
            result=_result(self.prepared_request),
            diagnostics={"source": "fake"},
        )

    def checkpoint(self) -> bytes:
        return b"checkpoint"

    def restore(self, payload: bytes) -> None:
        assert payload == b"checkpoint"

    def close(self) -> None:
        self.closed = True


def _request() -> CapabilityRequest:
    return CapabilityRequest(
        capability_id="environment.act",
        payload=environment_action_capability_payload("command", {"text": "open fridge"}),
        context=_context(),
        idempotency_key="turn-1",
    )


def test_effectful_environment_bridge_requires_generic_effect_executor() -> None:
    adapter = EnvironmentSessionCapabilityAdapter(_DurableEnvironment())
    with pytest.raises(RuntimeError, match="CapabilityEffectExecutor"):
        adapter.invoke(_request())


def test_prepared_bridge_preserves_outer_capability_identity_and_inner_environment_lineage() -> None:
    environment = _DurableEnvironment()
    adapter = EnvironmentSessionCapabilityAdapter(environment)
    request = _request()

    handle = adapter.prepare_capability_effect(request)
    assert handle.request_id == capability_effect_request_id(request)
    assert handle.request_digest == capability_request_digest(request)
    assert handle.provider_instance_id == "environment-provider-1"

    result = adapter.execute_prepared_capability(request, handle)
    assert result.request_digest == capability_request_digest(request)
    assert result.effect is not None
    assert result.effect.request_digest == capability_request_digest(request)
    assert result.effect.effect_class is EffectClass.RECONCILABLE
    assert result.effect.provider_receipt == "environment-receipt-1"
    assert result.payload["accepted"] is True
    assert result.payload["observation"]["payload"]["text"] == "done"

    assert environment.prepared_request is not None
    inner_digest = action_request_digest(environment.prepared_request)
    assert inner_digest != capability_request_digest(request)
    assert result.diagnostics["environment_effect"]["request_digest"] == inner_digest

    reconciliation = adapter.reconcile_prepared_capability(handle, _context())
    assert reconciliation.disposition.value == "applied"
    assert reconciliation.result is not None
    assert reconciliation.result.effect is not None
    assert reconciliation.result.effect.request_digest == capability_request_digest(request)
    assert reconciliation.result.diagnostics["environment_effect"]["request_digest"] == inner_digest


def test_environment_bridge_delegates_checkpoint_restore_and_close() -> None:
    environment = _DurableEnvironment()
    adapter = EnvironmentSessionCapabilityAdapter(environment)
    checkpoint = adapter.checkpoint()
    adapter.restore(checkpoint)
    adapter.close()
    assert environment.closed is True
