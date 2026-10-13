from __future__ import annotations

import json

from noetrium_platform.research.execution.workflow.composition.agent_context import (
    compile_agent_context,
)


def _jsonl_section(context: str):
    section = context.split("## ENVIRONMENT_CONTEXT\n", 1)[1].split("\n\n## ", 1)[0]
    return [json.loads(line) for line in section.splitlines()]


def test_mc_jsonl_feedback_has_one_authority_prefix_and_source_typed_world_records():
    facets = (
        {
            "label": "minecraft.holdings",
            "path": ("actor", "holdings"),
            "truth_class": "observed",
            "source": "environment.minecraft.authorized_observation",
            "validity": {"generation": "g1", "temporal_scope": "at_observation"},
            "evidence_ref": "observation-17",
            "value": {"item_counts": {"diamond": 2}},
        },
        {
            "label": "minecraft.last_action_feedback",
            "path": ("execution", "last"),
            "truth_class": "evidenced",
            "source": "environment.minecraft.authorized_observation",
            "validity": {"generation": "g1"},
            "value": {"outcome": {"status": "partial", "code": "HAZARD_OBSERVED"}},
        },
    )
    result = compile_agent_context({
        "goal": {"goal": "Collect 4 diamonds"},
        "environment": {
            "agent_context_format": "jsonl",
            "agent_context_facets": facets,
        },
        "capabilities": {"actions": {"columns": ["action_type"], "rows": [["collect_block"]]}},
        "memory": {"recalled": {"diamond": 999}},
    })
    rows = _jsonl_section(result.text)
    assert len(rows) == 3
    assert rows[0]["record"] == "capability_catalog"
    assert rows[0]["truth"] == "authorized"
    assert rows[1]["path"] == ["actor", "holdings"]
    assert rows[1]["value"]["item_counts"] == {"diamond": 2}
    assert "evidence_ref" not in rows[1]
    assert "source" not in rows[1]
    assert "validity" not in rows[1]
    assert rows[2]["value"]["outcome"]["status"] == "partial"
    assert '"diamond":999' in result.text.split("## RETRIEVED_METHOD_MEMORY\n", 1)[1]
    assert all("999" not in json.dumps(row) for row in rows)


def test_mc_jsonl_unknown_effect_cannot_upgrade_stale_observation_into_truth():
    facets = [{
        "label": "minecraft.local_state",
        "path": ("world", "local"),
        "truth_class": "observed",
        "source": "environment.minecraft.authorized_observation",
        "validity": {"observation_id": "old", "generation": "world-generation"},
        "value": {"inventory": {"diamond": 0}},
    }]
    text = compile_agent_context({
        "goal": {"goal": "get diamond"},
        "environment": {
            "agent_context_format": "jsonl",
            "agent_context_facets": facets,
            "effect_receipt": {"certainty": "indeterminate"},
        },
    }).text
    rows = _jsonl_section(text)
    assert rows[1]["validity"] == "previous_snapshot_not_current_effect_proof"
    assert rows[1]["truth"] == "observed"


def test_real_session_visibility_cut_routes_directly_into_jsonl_model_context():
    from tests.test_minecraft_observation_policy_v1 import _session
    from noetrium_platform.foundation.kernel.kernel import canonical_digest

    session, world, _events = _session(("health", "inventory"))
    observation = session._observation(payload={
        "kind": "minecraft_snapshot",
        "state": world,
        "state_digest": canonical_digest(world),
        "decision_view": {
            "kind": "minecraft_decision_view.v1",
            "state": world,
        },
        "bridge_diagnostics": {
            "hidden_rule": "private-recipe-do-not-leak",
        },
    })
    assert observation.payload["agent_context_format"] == "jsonl"
    text = compile_agent_context({
        "goal": {"goal": "Get an iron pickaxe"},
        "environment": dict(observation.payload),
    }).text
    rows = _jsonl_section(text)
    assert rows[0]["source"] == "authority"
    assert any(
        row.get("path") == ["actor", "holdings"]
        and row["value"]["item_counts"] == {"iron_hoe": 1}
        for row in rows
    )
    assert "private-recipe-do-not-leak" not in text
    assert "mirror-m05-recipe" not in text
    assert all(
        row["truth"] in {"declared", "authorized", "observed", "evidenced"}
        for row in rows
    )


def test_source_decision_constraint_is_control_metadata_not_model_payload():
    facets = ({
        "label": "environment.reference",
        "path": ("knowledge", "reference"),
        "truth_class": "declared",
        "source": "environment.example",
        "decision_constraint": {
            "kind": "declared_dependency",
            "requirements": {"opaque_input": 2},
            "valid_until": "physical_effect",
        },
        "value": {"unresolved_inputs": {"opaque_input": 2}},
    },)
    text = compile_agent_context({
        "goal": {"goal": "continue"},
        "environment": {
            "agent_context_format": "jsonl",
            "agent_context_facets": facets,
        },
    }).text
    rows = _jsonl_section(text)
    assert rows[1]["value"] == {"unresolved_inputs": {"opaque_input": 2}}
    assert "decision_constraint" not in rows[1]
    assert "valid_until" not in text
