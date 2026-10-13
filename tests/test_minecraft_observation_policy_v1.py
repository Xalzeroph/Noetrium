from __future__ import annotations

from types import SimpleNamespace
import unittest

from noetrium_platform.capabilities.environment.minecraft.api import (
    minecraft_environment_unit, minecraft_environment_visible_state_fields,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
    MinecraftEnvironmentSession,
)
from noetrium_platform.capabilities.environment.api import (
    ActionResult, EnvironmentQuery, EnvironmentCapabilityUnsupported,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, canonical_digest,
)


def _session(fields):
    unit = minecraft_environment_unit(
        "minecraft", "1.21.1", visible_state_fields=fields
    )
    instance = object.__new__(MinecraftEnvironmentSession)
    instance._visible_state_fields = minecraft_environment_visible_state_fields(unit)
    instance._closed = False
    instance._restore_faulted = False
    instance._projection_faulted = False
    instance._last_observation = None
    instance.session_id = "private-observation"
    instance.identity = SimpleNamespace(artifact_digest="a"*64)
    instance._observation_sequence = 0
    state = {
        "position": {"x": 8, "y": 63, "z": 6},
        "health": 19,
        "inventory": {"iron_hoe": 1},
        "nearby_entities": {"rows": [["chicken", 2]]},
        "last_outcome": {"secret": "mirror-m05-recipe"},
    }
    instance._state = SimpleNamespace(
        snapshot_with_digest=lambda: (state, canonical_digest(state)),
        snapshot_digest=lambda: canonical_digest(state),
        compact=lambda: state,
        decision_view=lambda detailed_entities=False: state,
    )
    events = []
    instance._diagnostic_recorder = SimpleNamespace(
        event=lambda *args, **kwargs: events.append((args,kwargs)),
    )
    return instance, state, events


def test_unrestricted_observation_preserves_standard_provider_output():
    instance, world, _ = _session(None)
    raw = {"kind": "minecraft_snapshot", "state": world,
           "events": [{"private": "full-audit"}],
           "bridge_diagnostics": {"debug": True}}
    projected = instance._agent_observation_payload(raw)
    assert {key: value for key, value in projected.items()
            if key not in {"agent_context_facets", "agent_context_format"}} == raw
    assert projected["agent_context_format"] == "jsonl"
    assert projected["agent_context_facets"]
    assert any(facet["label"] == "minecraft.holdings"
               for facet in projected["agent_context_facets"])
    assert "mirror-m05-recipe" not in str(projected["agent_context_facets"])
    assert instance._visible_state_fields is None


def test_restricted_projection_removes_all_raw_observation_bypasses():
    instance, world, events = _session(("health", "inventory"))
    payload = {
        "kind": "minecraft_action_result", "action_id": "step-7",
        "action_type": "craft_grid",
        "state": world, "state_digest": canonical_digest(world),
        "events": [{"rule_manifest": "M05: hidden recipe"}],
        "bridge_diagnostics": {"secret": "M05"},
        "context": {"task_id": "secret-task-m05"},
        "decision_view": {"kind":"minecraft_decision_view.v1","state":world},
    }
    observed = instance._observation(payload=payload, artifact_refs=("secret-artifact",))
    output = observed.payload
    assert output["state"] == {"health": 19, "inventory": {"iron_hoe": 1}}
    assert output["decision_view"]["state"] == output["state"]
    assert output["state_digest"] == canonical_digest(output["state"])
    assert output["state_digest"] != payload["state_digest"]
    assert observed.artifact_refs == ()
    for key in ("events", "bridge_diagnostics", "context"):
        assert key not in output
    assert "M05" not in str(output)
    assert "secret-task" not in str(output)
    assert any(args[1] == "MC_OBSERVED_WORLD_UNIT" for args, _ in events)
    assert "M05" not in str(events)


def test_restricted_action_result_does_not_leak_private_provider_outcome():
    instance, _, _ = _session(("health",))
    original = ActionResult(
        action_id="test", accepted=True, observation=None, effect=None,
        diagnostics={
            "environment": "minecraft", "action_type": "craft_grid",
            "effect_disposition": "applied",
            "provider_outcome": {"private": "changed-hidden-recipe"},
            "world_transition_digest": "full-secret-digest",
            "bridge_acknowledged": True,
        }
    )
    result = instance._agent_action_result(original)
    assert result.accepted is True
    assert result.diagnostics["effect_disposition"] == "applied"
    assert "provider_outcome" not in result.diagnostics
    assert "world_transition_digest" not in result.diagnostics
    assert "changed-hidden-recipe" not in str(result)


def test_restricted_state_and_task_queries_cannot_bypass_observation_policy():
    instance, world, _ = _session(("health",))
    context = ExecutionContext("run", "trace", "span", task_id="rule-suite-m05")
    state = instance.query(EnvironmentQuery("query-state", "state", {}, context))
    assert state.payload["state"] == {"health": 19}
    assert "position" not in str(state.payload)
    assert state.payload["state_digest"] == canonical_digest({"health": 19})
    task = instance.query(EnvironmentQuery("query-task", "task", {}, context))
    assert "task_id" not in task.payload
    assert task.payload["opaque_task_ref"].startswith("task:")
    assert "m05" not in str(task.payload).lower()
    assert task.payload["state_digest"] == state.payload["state_digest"]
    with unittest.TestCase().assertRaises(EnvironmentCapabilityUnsupported):
        instance.query(EnvironmentQuery("query-entity", "entity", {}, context))


def test_empty_observation_field_cut_hides_every_world_fact():
    instance, _, _ = _session(())
    assert instance._agent_observation_payload(
        {"kind": "minecraft_snapshot", "state": {"health": 20, "inventory": {"diamond": 1}}}
    )["state"] == {}
    assert instance._visible_state_fields == frozenset()
    with unittest.TestCase().assertRaisesRegex(ValueError, "visible_state_fields"):
        minecraft_environment_unit(
            "minecraft", "1.21.1", visible_state_fields=("health", "health")
        )


def test_capability_catalog_obeys_the_same_action_and_state_visibility_cut():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_action_catalog,
    )
    instance, world, _ = _session(("health",))
    environment = minecraft_environment_unit(
        "minecraft", "1.21.1",
        allowed_action_types=("observe_blocks", "craft_grid"),
        visible_state_fields=("health",),
    )
    instance.implementation = SimpleNamespace(environment=environment)
    descriptors = instance.capability_descriptors()
    assert len(descriptors) == 1
    catalog = descriptors[0]
    assert set(catalog.action_types) == {"observe_blocks", "craft_grid"}
    assert "entity" not in catalog.query_types
    assert {x["action_type"] for x in catalog.metadata["action_contracts"]} == {
        "observe_blocks", "craft_grid"
    }
    assert catalog.metadata["state_digest"] == canonical_digest({"health": 19})
    context = ExecutionContext("run", "trace", "span", task_id="mirror-m05")
    queried = instance.query(
        EnvironmentQuery("query-capabilities", "capabilities", {}, context)
    )
    assert "entity" not in queried.payload["capabilities"][0]["query_types"]
    assert "mirror-m05" not in str(queried.payload)
    assert "craft_grid" in queried.payload["capabilities"][0]["action_types"]


def test_passive_paper_world_allows_empty_agent_action_set_without_fake_tool():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_environment_allowed_action_types,
    )
    environment = minecraft_environment_unit(
        "minecraft", "1.21.1", allowed_action_types=(),
        visible_state_fields=("health",),
    )
    assert minecraft_environment_allowed_action_types(environment) == frozenset()
    instance, _, _ = _session(("health",))
    instance.implementation = SimpleNamespace(environment=environment)
    descriptor = instance.capability_descriptors()[0]
    assert descriptor.action_types == ()
    assert descriptor.query_types


def test_unrestricted_facets_do_not_republish_entities_omitted_by_decision_cut():
    instance, world, _ = _session(None)
    decision_state = dict(world)
    decision_state.pop("nearby_entities")
    projected = instance._agent_observation_payload({
        "kind": "minecraft_action_result",
        "state": world,
        "decision_view": {
            "kind": "minecraft_decision_view.v1",
            "state": decision_state,
        },
    })
    local = next(
        facet["value"] for facet in projected["agent_context_facets"]
        if facet["label"] == "minecraft.local_state"
    )
    assert "nearby_entities" not in local
    assert projected["state"]["nearby_entities"] == world["nearby_entities"]


def test_restricted_facets_do_not_republish_entities_omitted_by_decision_cut():
    instance, world, _ = _session(("health", "nearby_entities"))
    decision_state = dict(world)
    decision_state.pop("nearby_entities")
    projected = instance._agent_observation_payload({
        "kind": "minecraft_action_result",
        "state": world,
        "decision_view": {
            "kind": "minecraft_decision_view.v1",
            "state": decision_state,
        },
    })
    local = next(
        facet["value"] for facet in projected["agent_context_facets"]
        if facet["label"] == "minecraft.local_state"
    )
    assert "nearby_entities" not in local
    assert "nearby_entities" in projected["state"]
    assert "nearby_entities" not in projected["decision_view"]["state"]
