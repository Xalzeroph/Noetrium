from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentSpec,
    MinecraftReconciliation,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
    MinecraftActionCoordinator,
    MinecraftActionCoordinatorBindings,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.checkpoint import MinecraftActionVerification
from noetrium_platform.capabilities.environment.minecraft.runtime.errors import MinecraftEnvironmentFailure
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext


class _Bridge:
    def __init__(self, disposition: ActionReconciliationDisposition = ActionReconciliationDisposition.UNKNOWN) -> None:
        self.disposition = disposition
        self.commands = 0
        self.reconciliations: list[tuple[str, str | None]] = []

    def command(self, command, payload, *, timeout_s):
        self.commands += 1
        raise AssertionError(f"unexpected command: {command}")

    def reconcile_action(self, action_id, *, request, context, request_digest=None):
        self.reconciliations.append((action_id, request_digest))
        return MinecraftReconciliation(action_id, self.disposition, {"source": "unit"})


def _coordinator(bridge: _Bridge) -> MinecraftActionCoordinator:
    spec = MinecraftEnvironmentSpec(
        endpoint=MinecraftEndpointSpec(),
        bridge=MinecraftBridgeSpec(command=("fake-node",), cwd="."),
    )
    return MinecraftActionCoordinator(
        session_id="session",
        generation="a" * 64,
        provider_instance_id="minecraft:session",
        spec=spec,
        bridge=bridge,
        bindings=MinecraftActionCoordinatorBindings(
            event_log=lambda *args, **kwargs: None,
            failure_log=lambda *args, **kwargs: None,
            ingest_events=lambda *args, **kwargs: None,
            observation=lambda **kwargs: None,
            state_payload=lambda: {},
            last_observation=lambda: None,
        ),
    )


def _request(action_id: str = "action-1") -> ActionRequest:
    return ActionRequest(
        action_id,
        "wait",
        {"ms": 1},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )


def test_replace_restores_ledger_identity_without_touching_bridge() -> None:
    bridge = _Bridge()
    coordinator = _coordinator(bridge)
    request = _request()
    coordinator.replace({
        request.action_id: MinecraftActionVerification(
            request_digest=action_request_digest(request), accepted=True, verified=True
        )
    })

    with pytest.raises(ActionIdentityViolation, match="already executed"):
        coordinator.act(request)

    assert bridge.commands == 0
    assert len(coordinator) == 1


def test_snapshot_is_defensive_and_replace_owns_new_ledger() -> None:
    coordinator = _coordinator(_Bridge())
    request = _request()
    verification = MinecraftActionVerification(
        request_digest=action_request_digest(request), accepted=False, verified=None
    )
    coordinator.replace({request.action_id: verification})

    snapshot = coordinator.snapshot()
    snapshot.clear()

    assert len(coordinator) == 1
    assert coordinator.snapshot()[request.action_id] == verification


def test_prepared_unknown_reconciliation_returns_no_action_result() -> None:
    bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    coordinator = _coordinator(bridge)
    request = _request("prepared-1")
    handle = coordinator.prepare_action_recovery(request, request.context)

    result = coordinator.reconcile_prepared_action(handle, request.context)

    assert result.disposition is ActionReconciliationDisposition.UNKNOWN
    assert result.result is None
    assert bridge.reconciliations == [(request.action_id, handle.request_digest)]


def test_coordinator_bindings_are_frozen_and_constructor_is_narrow() -> None:
    bindings = MinecraftActionCoordinatorBindings(
        event_log=lambda *args, **kwargs: None,
        failure_log=lambda *args, **kwargs: None,
        ingest_events=lambda *args, **kwargs: None,
        observation=lambda **kwargs: None,
        state_payload=lambda: {},
        last_observation=lambda: None,
    )

    with pytest.raises(FrozenInstanceError):
        bindings.state_payload = lambda: {"mutated": True}  # type: ignore[misc]

    import inspect

    parameters = inspect.signature(MinecraftActionCoordinator).parameters
    assert "bindings" in parameters
    assert not {
        "event_log",
        "failure_log",
        "ingest_events",
        "observation",
        "state_payload",
        "last_observation",
    }.intersection(parameters)


def test_reconcile_not_applied_maps_to_no_effect() -> None:
    bridge = _Bridge(ActionReconciliationDisposition.NOT_APPLIED)
    coordinator = _coordinator(bridge)
    request = _request("not-applied-1")
    effect = EffectReceipt(
        effect_id="minecraft-action:not-applied-1",
        request_digest=action_request_digest(request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.EFFECT_POSSIBLE,
        provider_instance_id="minecraft:session",
        verification_required=True,
        provider_receipt=request.action_id,
    )
    reconciled = coordinator.reconcile(effect, request.context)
    assert reconciled.certainty is EffectCertainty.NO_EFFECT


@pytest.mark.parametrize(
    ("disposition", "expected_certainty"),
    (
        (ActionReconciliationDisposition.APPLIED, EffectCertainty.EFFECT_CONFIRMED),
        (ActionReconciliationDisposition.REJECTED, EffectCertainty.EFFECT_REJECTED),
        (ActionReconciliationDisposition.NOT_APPLIED, EffectCertainty.NO_EFFECT),
    ),
)
def test_prepared_and_generic_reconciliation_have_terminal_certainty_parity(
    disposition: ActionReconciliationDisposition,
    expected_certainty: EffectCertainty,
) -> None:
    context = ExecutionContext("run", "trace", "span", task_id="task")

    prepared_bridge = _Bridge(disposition)
    prepared_coordinator = _coordinator(prepared_bridge)
    prepared_request = _request(f"prepared-{disposition.value}")
    handle = prepared_coordinator.prepare_action_recovery(prepared_request, context)
    prepared = prepared_coordinator.reconcile_prepared_action(handle, context)
    assert prepared.disposition is disposition
    assert prepared.result is not None
    assert prepared.result.effect is not None
    assert prepared.result.effect.certainty is expected_certainty

    generic_bridge = _Bridge(disposition)
    generic_coordinator = _coordinator(generic_bridge)
    generic_request = _request(f"generic-{disposition.value}")
    effect = EffectReceipt(
        effect_id=f"minecraft-action:{generic_request.action_id}",
        request_digest=action_request_digest(generic_request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.EFFECT_POSSIBLE,
        provider_instance_id="minecraft:session",
        verification_required=True,
        provider_receipt=generic_request.action_id,
    )
    generic = generic_coordinator.reconcile(effect, context)
    assert generic.certainty is expected_certainty


def test_prepared_and_generic_unknown_reconciliation_both_fail_closed() -> None:
    context = ExecutionContext("run", "trace", "span", task_id="task")
    prepared_bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    prepared_coordinator = _coordinator(prepared_bridge)
    prepared_request = _request("prepared-unknown-parity")
    handle = prepared_coordinator.prepare_action_recovery(prepared_request, context)
    prepared = prepared_coordinator.reconcile_prepared_action(handle, context)
    assert prepared.disposition is ActionReconciliationDisposition.UNKNOWN
    assert prepared.result is None

    generic_bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    generic_coordinator = _coordinator(generic_bridge)
    generic_request = _request("generic-unknown-parity")
    effect = EffectReceipt(
        effect_id=f"minecraft-action:{generic_request.action_id}",
        request_digest=action_request_digest(generic_request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.EFFECT_POSSIBLE,
        provider_instance_id="minecraft:session",
        verification_required=True,
        provider_receipt=generic_request.action_id,
    )
    with pytest.raises(
        MinecraftEnvironmentFailure,
        match="cannot prove whether the external action was applied",
    ):
        generic_coordinator.reconcile(effect, context)
