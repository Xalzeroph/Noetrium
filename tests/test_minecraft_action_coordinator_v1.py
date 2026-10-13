from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftReconciliation,
    minecraft_action_authorization_unit,
    minecraft_action_invocation_unit,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
    MinecraftActionCoordinator,
    MinecraftActionCoordinatorBindings,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.checkpoint import MinecraftActionResolution
from noetrium_platform.capabilities.environment.minecraft.runtime.errors import MinecraftEnvironmentFailure
from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL


class _Bridge:
    def __init__(self, disposition: ActionReconciliationDisposition = ActionReconciliationDisposition.UNKNOWN) -> None:
        self.disposition = disposition
        self.commands = 0
        self.prepares: list[tuple[str, str, str, str, str]] = []
        self.reconciliations: list[tuple[str, str | None, str, str]] = []

    def command(self, command, payload, *, timeout_s, control=None):
        self.commands += 1
        raise AssertionError(f"unexpected command: {command}")

    def prepare_action(
        self, action_id, *, request_digest, action_type,
        invocation_unit_digest, authorization_unit_digest,
    ):
        self.prepares.append((
            action_id, request_digest, action_type,
            invocation_unit_digest, authorization_unit_digest,
        ))

    def reconcile_action(
        self, action_id, *, request, context, request_digest=None,
        invocation_unit_digest, authorization_unit_digest,
    ):
        self.reconciliations.append((
            action_id, request_digest,
            invocation_unit_digest, authorization_unit_digest,
        ))
        return MinecraftReconciliation(action_id, self.disposition, {"source": "unit"})


def _coordinator(bridge: _Bridge) -> MinecraftActionCoordinator:
    return MinecraftActionCoordinator(
        session_id="session",
        generation="a" * 64,
        provider_instance_id="minecraft:session",
        command_timeout_s=45.0,
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


def _seed_unknown_action(
    coordinator: MinecraftActionCoordinator, request: ActionRequest
) -> None:
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=MINECRAFT_ACTION_TYPES,
        contract_validation="passed",
    )
    coordinator.replace({
        request.action_id: MinecraftActionResolution(
            request_digest=action_request_digest(request),
            disposition=ActionReconciliationDisposition.UNKNOWN,
            invocation_unit_digest=invocation.unit_digest,
            authorization_unit_digest=authorization.unit_digest,
        )
    })


def test_replace_restores_ledger_identity_without_touching_bridge() -> None:
    bridge = _Bridge()
    coordinator = _coordinator(bridge)
    request = _request()
    coordinator.replace({
        request.action_id: MinecraftActionResolution(
            request_digest=action_request_digest(request), disposition=ActionReconciliationDisposition.APPLIED
        )
    })

    with pytest.raises(ActionIdentityViolation, match="already executed"):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)

    assert bridge.commands == 0
    assert len(coordinator) == 1


def test_snapshot_is_defensive_and_replace_owns_new_ledger() -> None:
    coordinator = _coordinator(_Bridge())
    request = _request()
    resolution = MinecraftActionResolution(
        request_digest=action_request_digest(request), disposition=ActionReconciliationDisposition.UNKNOWN
    )
    coordinator.replace({request.action_id: resolution})

    snapshot = coordinator.snapshot()
    snapshot.clear()

    assert len(coordinator) == 1
    assert coordinator.snapshot()[request.action_id] == resolution


def test_prepared_unknown_reconciliation_returns_indeterminate_action_result() -> None:
    bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    coordinator = _coordinator(bridge)
    request = _request("prepared-1")
    handle = coordinator.prepare_action_recovery(
        request,
        request.context,
        UNBOUNDED_EXECUTION_CONTROL,
    )

    result = coordinator.reconcile_prepared_action(
        handle,
        request.context,
        UNBOUNDED_EXECUTION_CONTROL,
    )

    assert result.disposition is ActionReconciliationDisposition.UNKNOWN
    assert result.result is not None
    assert result.result.effect is not None
    assert result.result.effect.certainty is EffectCertainty.INDETERMINATE
    assert len(bridge.prepares) == 1
    assert bridge.prepares[0][:3] == (
        request.action_id, action_request_digest(request), request.action_type
    )
    assert all(len(value) == 64 for value in bridge.prepares[0][3:])
    assert len(bridge.reconciliations) == 1
    assert bridge.reconciliations[0][:2] == (
        request.action_id, action_request_digest(request)
    )
    assert bridge.reconciliations[0][2:] == bridge.prepares[0][3:]



def test_prepared_contract_rejection_is_durable_and_never_reaches_bridge() -> None:
    bridge = _Bridge()
    coordinator = _coordinator(bridge)
    request = ActionRequest(
        "contract-rejected-1",
        "attack_nearest",
        {"entity": "zombie", "max_hits": 100},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )

    handle = coordinator.prepare_action_recovery(
        request,
        request.context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert bridge.prepares == []
    assert bridge.commands == 0

    executed = coordinator.execute_prepared_action(
        request,
        handle,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert executed.accepted is False
    assert executed.effect is not None
    assert executed.effect.certainty is EffectCertainty.EFFECT_REJECTED
    assert executed.diagnostics["contract_rejection_code"] == "FIELD_RANGE"
    assert bridge.commands == 0

    reconciled = coordinator.reconcile_prepared_action(
        handle,
        request.context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert reconciled.disposition is ActionReconciliationDisposition.REJECTED
    assert reconciled.result is not None
    assert reconciled.result.effect is not None
    assert reconciled.result.effect.certainty is EffectCertainty.EFFECT_REJECTED
    assert bridge.reconciliations == []
    assert bridge.commands == 0


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
    _seed_unknown_action(coordinator, request)
    effect = EffectReceipt(
        effect_id="minecraft-action:not-applied-1",
        request_digest=action_request_digest(request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.INDETERMINATE,
        provider_instance_id="minecraft:session",
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
    handle = prepared_coordinator.prepare_action_recovery(
        prepared_request,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    prepared = prepared_coordinator.reconcile_prepared_action(
        handle,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert prepared.disposition is disposition
    assert prepared.result is not None
    assert prepared.result.effect is not None
    assert prepared.result.effect.certainty is expected_certainty

    generic_bridge = _Bridge(disposition)
    generic_coordinator = _coordinator(generic_bridge)
    generic_request = _request(f"generic-{disposition.value}")
    _seed_unknown_action(generic_coordinator, generic_request)
    effect = EffectReceipt(
        effect_id=f"minecraft-action:{generic_request.action_id}",
        request_digest=action_request_digest(generic_request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.INDETERMINATE,
        provider_instance_id="minecraft:session",
        provider_receipt=generic_request.action_id,
    )
    generic = generic_coordinator.reconcile(effect, context)
    assert generic.certainty is expected_certainty


def test_prepared_and_generic_unknown_reconciliation_return_indeterminate_receipts() -> None:
    context = ExecutionContext("run", "trace", "span", task_id="task")
    prepared_bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    prepared_coordinator = _coordinator(prepared_bridge)
    prepared_request = _request("prepared-unknown-parity")
    handle = prepared_coordinator.prepare_action_recovery(
        prepared_request,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    prepared = prepared_coordinator.reconcile_prepared_action(
        handle,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert prepared.disposition is ActionReconciliationDisposition.UNKNOWN
    assert prepared.result is not None
    assert prepared.result.effect is not None
    assert prepared.result.effect.certainty is EffectCertainty.INDETERMINATE

    generic_bridge = _Bridge(ActionReconciliationDisposition.UNKNOWN)
    generic_coordinator = _coordinator(generic_bridge)
    generic_request = _request("generic-unknown-parity")
    _seed_unknown_action(generic_coordinator, generic_request)
    effect = EffectReceipt(
        effect_id=f"minecraft-action:{generic_request.action_id}",
        request_digest=action_request_digest(generic_request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.INDETERMINATE,
        provider_instance_id="minecraft:session",
        provider_receipt=generic_request.action_id,
    )
    generic = generic_coordinator.reconcile(effect, context)
    assert generic.certainty is EffectCertainty.INDETERMINATE


class _DeadlineCaptureBridge(_Bridge):
    terminal_settlement_timeout_s = 6.0

    def __init__(self):
        super().__init__()
        self.seconds = None
        self.wire_ms = None
        self.provider_window_ms = None

    def command(self, command, payload, *, timeout_s, control=None):
        self.commands += 1
        self.seconds = timeout_s
        self.wire_ms = payload['_action_timeout_ms']
        self.provider_window_ms = payload['_action_provider_window_ms']
        raise ValueError('simulated bridge failure')


class _FiniteActionControl(type(UNBOUNDED_EXECUTION_CONTROL)):
    @property
    def remaining_seconds(self) -> float:
        return 231.25


def test_action_bridge_caps_scope_by_catalog_liveness_deadline():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(_request('long-action'), _FiniteActionControl())
    # The request helper uses an action with the default 1x catalog timeout.
    # The outer scientific Scope remains authoritative when tighter, but it
    # cannot grant one bounded action more than its catalog liveness budget.
    assert bridge.seconds == 45.0
    assert bridge.wire_ms == 39000
    assert bridge.provider_window_ms == 39000


class _TighterFiniteActionControl(type(UNBOUNDED_EXECUTION_CONTROL)):
    @property
    def remaining_seconds(self) -> float:
        return 12.5


def test_action_bridge_preserves_tighter_outer_scope_deadline():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(_request('short-scope-action'), _TighterFiniteActionControl())
    assert bridge.seconds == 12.5
    assert bridge.wire_ms == 6500
    assert bridge.provider_window_ms == 6500



class _InsufficientSettlementControl(type(UNBOUNDED_EXECUTION_CONTROL)):
    @property
    def remaining_seconds(self) -> float:
        return 5.5


def test_action_fails_before_physical_submit_when_scope_cannot_fit_terminal_settlement():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    assert coordinator.minimum_action_execution_seconds == pytest.approx(6.001)
    with pytest.raises(
        MinecraftEnvironmentFailure,
        match="remaining action budget cannot contain provider terminal settlement",
    ) as failure:
        coordinator.act(_request("insufficient-settlement"), _InsufficientSettlementControl())
    assert failure.value.cause_code == "MINECRAFT_ACTION_SETTLEMENT_BUDGET_EXHAUSTED"
    assert bridge.commands == 0
    assert coordinator.snapshot() == {}

def test_collect_block_scope_is_capped_by_four_x_catalog_timeout():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    request = ActionRequest(
        "bounded-collect",
        "collect_block",
        {"block": "oak_log", "count": 2, "max_distance": 16},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(request, _FiniteActionControl())
    assert bridge.seconds == 180.0
    assert bridge.wire_ms == 174000
    # A composite action owns four base liveness windows in total, but one
    # physical provider primitive never inherits all four windows.
    assert bridge.provider_window_ms == 39000


def test_unbounded_action_retains_standalone_watchdog():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(_request('standalone-action'), UNBOUNDED_EXECUTION_CONTROL)
    assert bridge.seconds == 45.0
    assert bridge.wire_ms == 39000
    assert bridge.provider_window_ms == 39000




def test_unacknowledged_action_is_fenced_until_authoritative_reconciliation():
    bridge = _DeadlineCaptureBridge()
    coordinator = _coordinator(bridge)
    request = _request("lost-ack")

    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)

    unresolved = coordinator.snapshot()[request.action_id]
    assert unresolved.request_digest == action_request_digest(request)
    assert unresolved.disposition is ActionReconciliationDisposition.UNKNOWN
    with pytest.raises(ActionIdentityViolation, match="already executed"):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)
    assert bridge.commands == 1

    bridge.disposition = ActionReconciliationDisposition.APPLIED
    effect = EffectReceipt(
        effect_id="minecraft-action:lost-ack",
        request_digest=action_request_digest(request),
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.INDETERMINATE,
        provider_instance_id="minecraft:session",
        provider_receipt=request.action_id,
    )
    resolved = coordinator.reconcile(effect, request.context)
    assert resolved.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert coordinator.snapshot()[request.action_id].disposition is ActionReconciliationDisposition.APPLIED
    assert len(bridge.reconciliations) == 1

    # Terminal truth is immutable and no second provider reconciliation occurs.
    bridge.disposition = ActionReconciliationDisposition.REJECTED
    again = coordinator.reconcile(effect, request.context)
    assert again.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert len(bridge.reconciliations) == 1


class _MissingEvidenceBridge(_Bridge):
    def command(self, command, payload, *, timeout_s, control=None):
        del command, payload, timeout_s, control
        self.commands += 1
        return type("BridgeResult", (), {"events": (), "diagnostics": {}})()


def test_ack_without_identity_bound_action_result_is_also_replay_fenced():
    bridge = _MissingEvidenceBridge()
    coordinator = _coordinator(bridge)
    request = _request("missing-effect-evidence")

    with pytest.raises(MinecraftEnvironmentFailure, match="identity-bound"):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)

    assert coordinator.snapshot()[request.action_id].disposition is ActionReconciliationDisposition.UNKNOWN
    with pytest.raises(ActionIdentityViolation, match="already executed"):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)
    assert bridge.commands == 1


def test_local_composite_prepare_rejects_unapproved_children_before_any_physical_effect() -> None:
    bridge = _Bridge()
    original = _coordinator(bridge)
    restricted = MinecraftActionCoordinator(
        session_id="session",
        generation="a" * 64,
        provider_instance_id="minecraft:session",
        command_timeout_s=45.0,
        bridge=bridge,
        bindings=original._bindings,
        allowed_action_types=frozenset({"excavate_region"}),
    )
    request = ActionRequest(
        "nested-action",
        "excavate_region",
        {"corner_a": {"x": 0, "y": 64, "z": 0}, "corner_b": {"x": 0, "y": 64, "z": 0}},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    handle = restricted.prepare_action_recovery(
        request, request.context, UNBOUNDED_EXECUTION_CONTROL,
    )
    result = restricted.execute_prepared_action(
        request, handle, UNBOUNDED_EXECUTION_CONTROL,
    )
    assert result.diagnostics["contract_rejection_code"] == "ACTION_CHILD_CAPABILITY_NOT_AUTHORIZED"
    assert bridge.commands == 0
    assert bridge.prepares == []


def test_bridge_ack_error_without_action_result_preserves_original_rejection_reason() -> None:
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MinecraftBridgeCommandResult,
    )

    class _AckErrorBridge(_Bridge):
        def command(self, command, payload, *, timeout_s, control=None):
            del command, payload, timeout_s, control
            self.commands += 1
            return MinecraftBridgeCommandResult(
                "wait",
                False,
                (),
                {
                    "error": "ACTION_CONTROL_IDENTITY_REQUIRED",
                    "ack": {
                        "verified": False,
                        "rejected": True,
                        "error": "ACTION_CONTROL_IDENTITY_REQUIRED",
                    },
                },
            )

    coordinator = _coordinator(_AckErrorBridge())
    request = _request("ack-error-preserved")
    with pytest.raises(
        MinecraftEnvironmentFailure,
        match="ACTION_CONTROL_IDENTITY_REQUIRED",
    ) as failure:
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)
    assert (
        failure.value.cause_code
        == "MINECRAFT_ACTION_BRIDGE_REJECTED_WITHOUT_EVIDENCE"
    )
