from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    Observation,
    EnvironmentCapabilityDescriptor,
    action_request_digest,
)
from noetrium_platform.composition.environment_capabilities import (
    EnvironmentCapabilityProvider,
)
from noetrium_platform.research.execution.workflow.api import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityRequest,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.effect.api import (
    intent_field,
    prepared_effect_handle,
    prepared_handle_field,
    record_field,
)


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
        control,
    ) -> NoetriumUnit:
        del context, control
        self.prepared_request = request
        return prepared_effect_handle(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema="fake-environment-action.v1",
            opaque_payload=b"prepared-environment-action",
            provider_instance_id="environment-provider-1",
        )

    def execute_prepared_action(
        self,
        request: ActionRequest,
        handle: NoetriumUnit,
        control,
    ) -> ActionResult:
        del control
        assert self.prepared_request is not None
        assert prepared_handle_field(handle, "request_id") == request.action_id
        assert prepared_handle_field(handle, "request_digest") == action_request_digest(request)
        return _result(request)

    def reconcile_prepared_action(
        self,
        handle: NoetriumUnit,
        context: ExecutionContext,
        control,
    ) -> ActionReconciliationResult:
        del context, control
        assert self.prepared_request is not None
        assert prepared_handle_field(handle, "request_id") == self.prepared_request.action_id
        return ActionReconciliationResult(
            action_id=prepared_handle_field(handle, "request_id"),
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



class _DescribedEnvironment(_DurableEnvironment):
    def capability_descriptors(self):
        return (
            EnvironmentCapabilityDescriptor(
                capability_id="minecraft.world",
                version="1",
                action_types=("collect_block",),
                metadata={
                    "minimum_action_execution_seconds": 6.001,
                    "action_contracts": (
                        {
                            "action_type": "collect_block",
                            "category": "resource",
                            "description": "Collect matching blocks.",
                            "arguments": "{block:string, count?:1..64}",
                            "mutates_world": True,
                        },
                    )
                },
            ),
        )


def test_environment_bridge_projects_provider_contract_metadata() -> None:
    adapter = EnvironmentCapabilityProvider(_DescribedEnvironment())
    descriptor = adapter.describe("environment.act")
    rows = descriptor.metadata["environment_capabilities"]
    assert rows[0]["capability_id"] == "minecraft.world"
    contract = rows[0]["metadata"]["action_contracts"][0]
    assert contract["action_type"] == "collect_block"
    assert contract["arguments"] == "{block:string, count?:1..64}"
    assert descriptor.metadata["action_minimum_execution_seconds"]["collect_block"] == 6.001
    assert descriptor.metadata["minimum_execution_seconds"] == 6.001

def test_effectful_environment_bridge_requires_generic_effect_executor() -> None:
    adapter = EnvironmentCapabilityProvider(_DurableEnvironment())
    with pytest.raises(RuntimeError, match="CapabilityEffectExecutor"):
        adapter.invoke(_request(), UNBOUNDED_EXECUTION_CONTROL)


def test_prepared_bridge_preserves_outer_capability_identity_and_inner_environment_lineage() -> None:
    environment = _DurableEnvironment()
    adapter = EnvironmentCapabilityProvider(environment)
    request = _request()

    handle = adapter.prepare_capability_effect(request, UNBOUNDED_EXECUTION_CONTROL)
    assert prepared_handle_field(handle, "request_id") == capability_effect_request_id(request)
    assert prepared_handle_field(handle, "request_digest") == capability_request_digest(request)
    assert prepared_handle_field(handle, "provider_instance_id") == "environment-provider-1"

    result = adapter.execute_prepared_capability(request, handle, UNBOUNDED_EXECUTION_CONTROL)
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

    reconciliation = adapter.reconcile_prepared_capability(handle, _context(), UNBOUNDED_EXECUTION_CONTROL)
    assert reconciliation.disposition.value == "applied"
    assert reconciliation.result is not None
    assert reconciliation.result.effect is not None
    assert reconciliation.result.effect.request_digest == capability_request_digest(request)
    assert reconciliation.result.diagnostics["environment_effect"]["request_digest"] == inner_digest


def test_environment_bridge_separates_decision_view_from_raw_evidence() -> None:
    class DecisionEnvironment(_DurableEnvironment):
        def execute_prepared_action(self, request, handle, control):
            del handle, control
            base = _result(request)
            return ActionResult(
                action_id=base.action_id,
                accepted=base.accepted,
                observation=Observation(
                    "obs-decision",
                    "env-gen-2",
                    {
                        "kind": "rich_environment_result",
                        "events": (
                            {"kind": "raw_event", "payload": {"large": "raw"}},
                        ),
                        "decision_view": {
                            "kind": "decision.v1",
                            "state": {"health": 20},
                        },
                    },
                    ("artifact-1",),
                ),
                effect=base.effect,
                diagnostics=base.diagnostics,
            )

    environment = DecisionEnvironment()
    adapter = EnvironmentCapabilityProvider(environment)
    request = _request()
    handle = adapter.prepare_capability_effect(request, UNBOUNDED_EXECUTION_CONTROL)
    result = adapter.execute_prepared_capability(request, handle, UNBOUNDED_EXECUTION_CONTROL)

    observation = result.payload["observation"]
    assert observation["payload"]["kind"] == "decision.v1"
    assert observation["payload"]["state"]["health"] == 20
    assert "events" not in observation["payload"]
    assert result.evidence["observation"]["payload"]["events"][0]["kind"] == "raw_event"
    assert result.evidence["observation"]["payload"]["decision_view"]["kind"] == "decision.v1"
    assert result.evidence["environment_diagnostics"] == {"won": True}
    assert "environment_diagnostics" not in observation["payload"]


def test_environment_bridge_delegates_checkpoint_restore_and_close() -> None:
    environment = _DurableEnvironment()
    adapter = EnvironmentCapabilityProvider(environment)
    checkpoint = adapter.checkpoint()
    adapter.restore(checkpoint)
    adapter.close()
    assert environment.closed is True
