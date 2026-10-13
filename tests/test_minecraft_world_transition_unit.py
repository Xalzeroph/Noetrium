from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_TYPES,
    MINECRAFT_ACTION_SPEC_BY_TYPE,
    MINECRAFT_CHILD_EFFECT_EVIDENCE_SCHEMA,
    MINECRAFT_TRANSITION_SCHEMA,
    minecraft_action_authorization_unit,
    minecraft_action_invocation_unit,
    minecraft_transition_unit,
)
from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit


def _sample(**override):
    action_type = str(override.pop("action_type", "collect_block"))
    action_id = str(override.pop("action_id", "action-1"))
    arguments = override.pop("action_arguments", {"block": "oak_log", "count": 1})
    request = ActionRequest(
        action_id,
        action_type,
        arguments,
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=MINECRAFT_ACTION_TYPES,
        contract_validation="passed",
    )
    fields = dict(
        invocation=invocation,
        authorization=authorization,
        provider_instance_id="minecraft:session",
        before_observation_id="minecraft:s:observation:1",
        after_observation_id="minecraft:s:observation:2",
        state_digest="b" * 64,
        outcome_status="partial",
        effect_disposition="applied",
        action_result_digest="c" * 64,
        effect_receipt_id="minecraft-action:action-1",
        bridge_acknowledged=True,
    )
    return minecraft_transition_unit(**(fields | override))


def _nested_child_effect_rows(invocation, authorization):
    child_id = "minecraft-skill-child:" + "d" * 64
    return (
        {
            "action_id": child_id,
            "request_digest": "d" * 64,
            "action_type": "collect_block",
            "parent_action_id": str(invocation.attributes["action_id"]),
            "parent_request_digest": str(invocation.attributes["request_digest"]),
            "step_index": 0,
            "depth": 1,
            "root_invocation_unit_digest": invocation.unit_digest,
            "authorization_unit_digest": authorization.unit_digest,
            "action_spec_unit_digest": MINECRAFT_ACTION_SPEC_BY_TYPE["collect_block"].unit_digest,
            "state": "terminal",
            "disposition": "applied",
            "outcome_status": "applied",
            "outcome_code": "BLOCK_REMOVED",
        },
    )


def test_transition_unit_preserves_four_disjoint_truth_classes_and_roundtrip() -> None:
    transition = _sample()
    assert transition.has_trait(MINECRAFT_TRANSITION_SCHEMA)
    assert {name for name, _ in transition.roles} == {
        "declared", "authorized", "observed", "evidenced"
    }
    assert transition.one_unit("declared").attributes["action_type"] == "collect_block"
    authorized = transition.one_unit("authorized").attributes
    assert authorized["authorization_state"] == "authorized"
    assert authorized["authority_kind"] == "capability_action_catalog"
    assert authorized["resource_authority_receipt"] is None
    observed = transition.one_unit("observed").attributes
    assert observed["state_digest"] == "b" * 64
    assert "effect_disposition" not in observed
    assert transition.one_unit("evidenced").attributes["effect_disposition"] == "applied"
    assert decode_unit(encode_unit(transition)).unit_digest == transition.unit_digest


def test_transition_lifts_nested_provider_wal_children_into_typed_evidence_units() -> None:
    request = ActionRequest(
        "local-excavation",
        "excavate_region",
        {"corner_a": {"x": 0, "y": 64, "z": 0}, "corner_b": {"x": 0, "y": 64, "z": 0}},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=MINECRAFT_ACTION_TYPES,
        contract_validation="passed",
    )
    transition = minecraft_transition_unit(
        invocation=invocation,
        authorization=authorization,
        provider_instance_id="minecraft:session",
        before_observation_id="observation:1",
        after_observation_id="observation:2",
        state_digest="f" * 64,
        outcome_status="applied",
        effect_disposition="applied",
        action_result_digest="a" * 64,
        effect_receipt_id="minecraft-action:local-excavation",
        bridge_acknowledged=True,
        child_effects=_nested_child_effect_rows(invocation, authorization),
    )
    evidenced = transition.one_unit("evidenced")
    children = evidenced.units("child_effect")
    assert evidenced.attributes["child_effect_count"] == 1
    assert [row.attributes["depth"] for row in children] == [1]
    assert [row.attributes["action_type"] for row in children] == ["collect_block"]
    assert all(row.has_schema(MINECRAFT_CHILD_EFFECT_EVIDENCE_SCHEMA) for row in children)
    assert children[0].one_unit("root_invocation").unit_digest == invocation.unit_digest
    assert children[0].one_unit("authorization").unit_digest == authorization.unit_digest
    assert children[0].one_unit("action_specification").unit_digest == (
        MINECRAFT_ACTION_SPEC_BY_TYPE["collect_block"].unit_digest
    )
    assert transition.attributes["version"] == 3
    assert decode_unit(encode_unit(transition)).unit_digest == transition.unit_digest


def test_transition_rejects_child_outside_authorized_unit_closure() -> None:
    import pytest

    request = ActionRequest(
        "craft-only",
        "craft_item",
        {"item": "stick", "count": 4},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=frozenset({"craft_item"}),
        contract_validation="passed",
    )
    child = {
        "action_id": "minecraft-skill-child:" + "d" * 64,
        "request_digest": "d" * 64,
        "action_type": "place_block",
        "parent_action_id": "craft-only",
        "parent_request_digest": str(invocation.attributes["request_digest"]),
        "step_index": 0,
        "depth": 1,
        "root_invocation_unit_digest": invocation.unit_digest,
        "authorization_unit_digest": authorization.unit_digest,
        "action_spec_unit_digest": MINECRAFT_ACTION_SPEC_BY_TYPE["place_block"].unit_digest,
        "state": "terminal",
        "disposition": "applied",
        "outcome_status": "applied",
        "outcome_code": "BLOCK_PLACED",
    }
    with pytest.raises(ValueError, match="outside the authorized Unit closure"):
        minecraft_transition_unit(
            invocation=invocation,
            authorization=authorization,
            provider_instance_id="minecraft:session",
            before_observation_id=None,
            after_observation_id="observation:2",
            state_digest="f" * 64,
            outcome_status="applied",
            effect_disposition="applied",
            action_result_digest="a" * 64,
            effect_receipt_id="minecraft-action:craft-only",
            bridge_acknowledged=True,
            child_effects=(child,),
        )


def test_transition_unit_identity_tracks_observed_evidence_and_not_hidden_world() -> None:
    original = _sample()
    changed = _sample(state_digest="d" * 64)
    assert original.unit_digest != changed.unit_digest
    assert original.one_unit("declared").unit_digest == changed.one_unit("declared").unit_digest


def test_executed_action_records_reconstructible_transition_without_exposing_audit_view():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MinecraftBridgeCommandResult,
        MinecraftObservationEvent,
    )
    from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
        MinecraftActionCoordinator,
        MinecraftActionCoordinatorBindings,
    )
    from noetrium_platform.capabilities.environment.api import ActionRequest, Observation
    from noetrium_platform.foundation.kernel.kernel import (
        ExecutionContext, canonical_bytes,
    )
    from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL

    events = []
    class Bridge:
        def command(self, command, payload, *, timeout_s, control=None):
            assert command == 'wait'
            assert timeout_s > 0
            action_id = payload['action_id']
            event = MinecraftObservationEvent('action_result', {
                'action_id': action_id,
                'request_digest': payload['_request_digest'],
                'action_invocation_unit_digest': payload['_action_invocation_unit_digest'],
                'action_authorization_unit_digest': payload['_action_authorization_unit_digest'],
                'action': {'tool': command},
                'outcome': {'status': 'applied', 'code': 'WAIT_COMPLETED'},
                'verified': True,
                'effect_disposition': 'applied',
            })
            return MinecraftBridgeCommandResult(command, True, (event,), {})

    def event_log(phase, event, **kwargs):
        events.append((event, kwargs.get('attributes', {})))

    def observe(*, payload, artifact_refs=()):
        return Observation('observation:2', 'g' * 64, payload, artifact_refs)

    coordinator = MinecraftActionCoordinator(
        session_id='sample', generation='g' * 64,
        provider_instance_id='provider:1', command_timeout_s=45,
        bridge=Bridge(),
        bindings=MinecraftActionCoordinatorBindings(
            event_log=event_log, failure_log=lambda *args, **kwargs: None,
            ingest_events=lambda *args, **kwargs: None,
            observation=observe,
            state_payload=lambda: {'state': {}, 'state_digest': 'b' * 64},
            last_observation=lambda: None,
        ),
    )
    request = ActionRequest('action-1', 'wait', {'ms': 1}, ExecutionContext('run', 'trace', 'span'))
    result = coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)
    assert result.accepted is True
    journal_rows = [attributes for name, attributes in events if name == 'MC_WORLD_TRANSITION']
    assert len(journal_rows) == 1
    reconstructed = decode_unit(canonical_bytes(journal_rows[0]['unit']))
    assert reconstructed.unit_digest == result.diagnostics['world_transition_digest']
    assert reconstructed.one_unit('observed').attributes['after_observation_id'] == 'observation:2'
    assert 'world_transition_digest' not in result.observation.payload


def test_unacknowledged_effect_is_neither_rejected_nor_fabricated_observation():
    from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
        MinecraftActionCoordinator, MinecraftActionCoordinatorBindings,
    )
    from noetrium_platform.capabilities.environment.minecraft.runtime.errors import MinecraftEnvironmentFailure
    from noetrium_platform.capabilities.environment.api import ActionRequest
    from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_bytes
    from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL
    import pytest

    history = []

    class Bridge:
        def command(self, command, payload, *, timeout_s, control=None):
            error = TimeoutError("no verified terminal response")
            error.cause_code = "BRIDGE_READ_TIMEOUT"
            raise error

    coordinator = MinecraftActionCoordinator(
        session_id="session", generation="g" * 64,
        provider_instance_id="provider:1", command_timeout_s=45,
        bridge=Bridge(),
        bindings=MinecraftActionCoordinatorBindings(
            event_log=lambda phase, event, **kwargs: history.append((event, kwargs.get("attributes", {}))),
            failure_log=lambda *args, **kwargs: None,
            ingest_events=lambda *args, **kwargs: None,
            observation=lambda **kwargs: pytest.fail("cannot fabricate observation on timeout"),
            state_payload=lambda: pytest.fail("cannot fabricate state on timeout"),
            last_observation=lambda: None,
        ),
    )
    request = ActionRequest("lost-ack", "wait", {"ms": 1}, ExecutionContext("run", "trace", "span"))
    with pytest.raises(MinecraftEnvironmentFailure):
        coordinator.act(request, UNBOUNDED_EXECUTION_CONTROL)
    transitions = [raw for kind, raw in history if kind == "MC_WORLD_TRANSITION"]
    assert len(transitions) == 1
    transition = decode_unit(canonical_bytes(transitions[0]["unit"]))
    observed = transition.one_unit("observed").attributes
    evidenced = transition.one_unit("evidenced").attributes
    assert observed["after_observation_id"] is None
    assert observed["state_digest"] is None
    assert evidenced["effect_disposition"] == "unknown"
    assert evidenced["action_result_digest"] is None
    assert evidenced["failure_code"] == "BRIDGE_READ_TIMEOUT"


def test_world_observation_unit_only_contains_legal_decision_projection():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MINECRAFT_OBSERVED_WORLD_SCHEMA, minecraft_observed_world_unit
    )
    visible = {"kind": "minecraft_decision_view.v1", "state": {"health": 20, "inventory": {"stone": 3}}}
    observed = minecraft_observed_world_unit(
        observation_id="minecraft:s:observation:1",
        generation="d" * 64,
        state_digest="f" * 64,
        decision_view=visible,
    )
    assert observed.has_trait(MINECRAFT_OBSERVED_WORLD_SCHEMA)
    assert observed.attributes["visible_projection"] == visible
    assert observed.attributes["observed_state_digest"] == "f" * 64
    assert "full_state_digest" not in observed.attributes
    assert "evaluator" not in observed.attributes
    assert decode_unit(encode_unit(observed)).unit_digest == observed.unit_digest


def test_session_observation_journals_unit_without_leaking_audit_to_agent():
    from types import SimpleNamespace
    from noetrium_platform.capabilities.environment.minecraft.runtime.session import MinecraftEnvironmentSession
    from noetrium_platform.foundation.kernel.kernel import canonical_bytes

    events = []
    visible = {"kind": "minecraft_decision_view.v1", "state": {"inventory": {"stone": 2}}}
    proxy = object.__new__(MinecraftEnvironmentSession)
    proxy.session_id = "unit-check"
    proxy.identity = SimpleNamespace(artifact_digest="c" * 64)
    proxy._visible_state_fields = None
    proxy._observation_sequence = 0
    proxy._last_observation = None
    proxy._decision_view = lambda: visible
    proxy._event_log = lambda phase, event, **kw: events.append((event, kw))
    observation = MinecraftEnvironmentSession._observation(proxy, payload={
        "kind": "minecraft_snapshot",
        "decision_view": visible,
        "state": {"inventory": {"stone": 2}},
        "state_digest": "e" * 64,
    })
    assert observation.payload["decision_view"] == visible
    assert "unit" not in observation.payload
    assert len(events) == 1
    assert events[0][0] == "MC_OBSERVED_WORLD_UNIT"
    journaled = decode_unit(canonical_bytes(events[0][1]["attributes"]["unit"]))
    assert journaled.attributes["observation_id"] == observation.observation_id
    assert journaled.attributes["visible_projection"] == visible


def test_transition_preserves_user_action_and_provider_constraints_in_separate_truths():
    transition = _sample(
        action_arguments={"block": "oak_log", "count": 3},
        provider_outcome={
            "status": "rejected",
            "code": "HARVEST_TOOL_REQUIRED",
            "prerequisites": {"acceptable_tools": ["stone_pickaxe"]},
        },
    )
    declared = transition.one_unit("declared").attributes
    evidenced = transition.one_unit("evidenced").attributes
    observed = transition.one_unit("observed").attributes
    assert declared["arguments"] == {"block": "oak_log", "count": 3}
    assert "prerequisites" not in declared
    assert evidenced["provider_outcome"]["prerequisites"]["acceptable_tools"] == ("stone_pickaxe",)
    assert "provider_outcome" not in observed
    assert decode_unit(encode_unit(transition)).unit_digest == transition.unit_digest


def test_world_unit_delta_tracks_observed_change_without_duplicating_full_view():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_observed_world_unit,
    )
    baseline = {
        "kind": "minecraft_decision_view.v1",
        "state": {
            "inventory": {"oak_log": 2},
            "health": 20,
            "position": {"x": 0, "y": 64, "z": 0},
        },
    }
    changed = {
        "kind": "minecraft_decision_view.v1",
        "state": {
            "inventory": {"oak_log": 3},
            "health": 20,
        },
    }
    first = minecraft_observed_world_unit(
        observation_id="observation:1", generation="generation-a",
        state_digest="a" * 64, decision_view=baseline,
    )
    second = minecraft_observed_world_unit(
        observation_id="observation:2", generation="generation-a",
        state_digest="b" * 64, decision_view=changed,
        base_observation_id="observation:1",
        base_decision_view=baseline,
    )
    assert first.attributes["representation"] == "snapshot"
    assert second.attributes["representation"] == "delta"
    assert second.attributes["base_observation_id"] == "observation:1"
    delta = second.attributes["visible_projection"]
    assert delta["changed"] == {"inventory": {"oak_log": 3}}
    assert delta["removed"] == ("position",) or delta["removed"] == ["position"]
    assert second.attributes["visible_projection_digest"] != first.attributes["visible_projection_digest"]
    assert decode_unit(encode_unit(second)).unit_digest == second.unit_digest


def test_world_unit_rejects_unbound_delta_before_any_commit():
    import pytest
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_observed_world_unit,
    )
    with pytest.raises(ValueError, match="identified base"):
        minecraft_observed_world_unit(
            observation_id="observation:2", generation="generation-a",
            state_digest="b" * 64,
            decision_view={"kind": "minecraft_decision_view.v1", "state": {}},
            base_decision_view={"kind": "minecraft_decision_view.v1", "state": {}},
        )


def test_action_result_rejects_forged_nested_child_causal_lineage():
    import pytest
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MinecraftObservationEvent, minecraft_action_result_record,
    )

    request = ActionRequest(
        "local-excavation",
        "excavate_region",
        {"corner_a": {"x": 0, "y": 64, "z": 0}, "corner_b": {"x": 0, "y": 64, "z": 0}},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=MINECRAFT_ACTION_TYPES,
        contract_validation="passed",
    )
    rows = list(_nested_child_effect_rows(invocation, authorization))
    rows[0] = {**rows[0], "parent_request_digest": "0" * 64}
    event = MinecraftObservationEvent(
        "action_result",
        {
            "action_id": request.action_id,
            "request_digest": str(invocation.attributes["request_digest"]),
            "action_invocation_unit_digest": invocation.unit_digest,
            "action_authorization_unit_digest": authorization.unit_digest,
            "action": {"tool": "excavate_region"},
            "outcome": {"status": "applied", "code": "REGION_EXCAVATED"},
            "verified": True,
            "effect_disposition": "applied",
            "child_effects": rows,
        },
        sequence=1,
    )
    with pytest.raises(ValueError, match="causal lineage"):
        minecraft_action_result_record(
            event,
            expected_action_id=request.action_id,
            expected_action_type="excavate_region",
            expected_request_digest=str(invocation.attributes["request_digest"]),
            expected_invocation_unit_digest=invocation.unit_digest,
            expected_authorization_unit_digest=authorization.unit_digest,
        )


def test_action_result_rejects_control_completion_that_contradicts_effect_truth():
    import pytest
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MinecraftObservationEvent, minecraft_action_result_record,
    )
    request_digest = "a" * 64
    invocation_digest = "b" * 64
    authorization_digest = "c" * 64
    base = {
        "action_id": "ac1",
        "request_digest": request_digest,
        "action_invocation_unit_digest": invocation_digest,
        "action_authorization_unit_digest": authorization_digest,
        "action": {"tool": "collect_block"},
        "outcome": {"status": "applied", "code": "BLOCK_COLLECTED"},
        "verified": True,
        "effect_disposition": "applied",
        "execution_control": {
            "state": "settled",
            "effect_disposition": "applied",
            "transitions": 3,
            "reason": None,
        },
    }
    good = MinecraftObservationEvent("action_result", base, sequence=1)
    minecraft_action_result_record(
        good, expected_action_id="ac1", expected_action_type="collect_block",
        expected_request_digest=request_digest,
        expected_invocation_unit_digest=invocation_digest,
        expected_authorization_unit_digest=authorization_digest,
    )
    forged = MinecraftObservationEvent(
        "action_result",
        {**base, "execution_control": {
            **base["execution_control"], "effect_disposition": "not_applied",
        }},
        sequence=2,
    )
    with pytest.raises(ValueError, match="contradicts"):
        minecraft_action_result_record(
            forged, expected_action_id="ac1", expected_action_type="collect_block",
            expected_request_digest=request_digest,
            expected_invocation_unit_digest=invocation_digest,
            expected_authorization_unit_digest=authorization_digest,
        )
