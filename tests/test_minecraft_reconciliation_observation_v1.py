"""A lost ACK needs new world observations, not fabricated effect certainty."""

from types import SimpleNamespace

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition, ActionReconciliationResult, ActionResult,
    Observation,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
    MinecraftEnvironmentSession,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    UNBOUNDED_EXECUTION_CONTROL,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty, EffectClass, EffectReceipt, ExecutionContext,
)


def _sample(disposition=ActionReconciliationDisposition.UNKNOWN):
    receipt = EffectReceipt(
        effect_id="effect-1",
        request_digest="a" * 64,
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.INDETERMINATE,
        provider_instance_id="provider-1",
    )
    return ActionReconciliationResult(
        action_id="action-1",
        disposition=disposition,
        result=ActionResult("action-1", False, None, receipt, {"original": "proof"}),
        diagnostics={"proof_source": "durable_action_journal"},
    )


def test_unknown_action_reconciliation_yields_new_read_only_world_snapshot():
    outcome = _sample()
    observation = Observation(
        "observation-after-uncertain-action",
        "g" * 64,
        {
            "kind": "minecraft_snapshot",
            "state": {"position": {"x": 3, "y": 64, "z": 8}},
            "decision_view": {
                "kind": "minecraft_decision_view.v1",
                "state": {"position": {"x": 3, "y": 64, "z": 8}},
            },
        },
    )
    events = []
    session = SimpleNamespace(
        _assert_open=lambda: None,
        _agent_action_result=lambda value: value,
        _visible_state_fields=None,
        _actions=SimpleNamespace(reconcile_prepared_action=lambda *args: outcome),
        observe=lambda context: observation,
        _event_log=lambda *args, **kw: events.append((args, kw)),
    )
    refreshed = MinecraftEnvironmentSession.reconcile_prepared_action(
        session,
        None,
        ExecutionContext("run", "trace", "span"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert refreshed.disposition is ActionReconciliationDisposition.UNKNOWN
    assert refreshed.result.effect.certainty is EffectCertainty.INDETERMINATE
    assert refreshed.result.observation == observation
    assert refreshed.result.accepted is False
    from noetrium_platform.composition.environment_capabilities.observation import (
        semantic_observation_payload,
    )
    projected = semantic_observation_payload(refreshed.result.observation)
    assert projected["payload"]["state"]["position"] == {"x": 3, "y": 64, "z": 8}
    assert "bridge_diagnostics" not in projected["payload"]
    assert refreshed.result.diagnostics["post_reconciliation_observation_is_effect_proof"] is False
    assert events[0][0][1] == "MC_RECONCILIATION_WORLD_REFRESHED"


def test_authoritatively_reconciled_effect_still_refreshes_current_agent_context():
    original = _sample(ActionReconciliationDisposition.APPLIED)
    observation = Observation(
        "observation-after-recovered-action",
        "g" * 64,
        {"kind": "minecraft_snapshot", "state": {"inventory": {"oak_log": 1}}},
    )
    session = SimpleNamespace(
        _assert_open=lambda: None,
        _agent_action_result=lambda value: value,
        _visible_state_fields=None,
        _actions=SimpleNamespace(reconcile_prepared_action=lambda *args: original),
        observe=lambda context: observation,
        _event_log=lambda *args, **kw: None,
    )
    observed = MinecraftEnvironmentSession.reconcile_prepared_action(
        session, None, ExecutionContext("run", "trace", "span"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert observed.disposition is ActionReconciliationDisposition.APPLIED
    assert observed.result.observation == observation
    assert observed.result.diagnostics["post_reconciliation_observation_is_effect_proof"] is False


def test_existing_reconciliation_observation_never_triggers_duplicate_refresh():
    original = _sample(ActionReconciliationDisposition.APPLIED)
    existing = Observation("already-current", "g" * 64, {"kind": "minecraft_snapshot", "state": {}})
    original = ActionReconciliationResult(
        original.action_id, original.disposition,
        ActionResult(
            original.result.action_id, original.result.accepted, existing,
            original.result.effect, original.result.diagnostics,
        ),
        original.diagnostics,
    )
    session = SimpleNamespace(
        _assert_open=lambda: None,
        _agent_action_result=lambda value: value,
        _visible_state_fields=None,
        _actions=SimpleNamespace(reconcile_prepared_action=lambda *args: original),
        observe=lambda context: (_ for _ in ()).throw(AssertionError("unexpected refresh")),
    )
    observed = MinecraftEnvironmentSession.reconcile_prepared_action(
        session, None, ExecutionContext("run", "trace", "span"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert observed == original


def test_snapshot_refresh_failure_cannot_overwrite_unknown_effect_proof():
    original = _sample()
    errors = []
    session = SimpleNamespace(
        _assert_open=lambda: None,
        _agent_action_result=lambda value: value,
        _visible_state_fields=None,
        _actions=SimpleNamespace(reconcile_prepared_action=lambda *args: original),
        observe=lambda context: (_ for _ in ()).throw(TimeoutError("snapshot unavailable")),
        _failure_log=lambda *args, **kw: errors.append((args, kw)),
    )
    result = MinecraftEnvironmentSession.reconcile_prepared_action(
        session, None, ExecutionContext("run", "trace", "span"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert result == original
    assert result.result.effect.certainty is EffectCertainty.INDETERMINATE
    assert errors[0][1]["code"] == "MINECRAFT_RECONCILIATION_OBSERVATION_UNAVAILABLE"
