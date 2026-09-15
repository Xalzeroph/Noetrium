import json

import pytest

from noetrium_platform.capabilities.participant.agent.api import (
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentSkillDescription,
)
from noetrium_platform.capabilities.participant.agent.runtime.model_view import (
    project_action_history,
)
from noetrium_platform.capabilities.participant.agent.runtime.prompt import (
    AgentPromptAssembler,
    AgentPromptBudgetExceeded,
    PromptBlock,
)


def _skill() -> AgentSkillDescription:
    return AgentSkillDescription(
        "collect_block",
        "minecraft",
        "collect one block",
        '{"block":"string","count":"int"}',
        True,
    )


def test_action_history_projection_keeps_complete_recent_records() -> None:
    source = tuple(
        {"action_id": f"action-{index}", "payload": {"value": "x" * 48}}
        for index in range(10)
    )
    projection = project_action_history(source, max_chars=620)

    document = json.loads(projection.text)
    receipt = projection.receipt
    assert 0 < receipt.included_count < receipt.source_count
    assert receipt.included_count + receipt.omitted_count == receipt.source_count
    assert receipt.compacted
    assert [row["action_id"] for row in document["actions"]] == [
        f"action-{index}"
        for index in range(receipt.first_included_index, receipt.source_count)
    ]
    assert all(len(value) == 64 for value in (
        receipt.source_digest,
        receipt.included_digest,
        receipt.omitted_digest,
    ))


def test_action_history_projection_never_emits_partial_json() -> None:
    projection = project_action_history(
        ({"action_id": "old", "payload": {"value": "x" * 100}},),
        max_chars=5,
    )
    assert projection.text == ""
    assert projection.receipt.included_count == 0
    assert projection.receipt.omitted_count == 1


def test_agent_prompt_assembler_compacts_history_without_slicing_host_facts() -> None:
    compiled = AgentPromptAssembler(max_chars=1200).compile(
        goal=AgentGoal("goal-1", "collect iron", {"target": "iron_ingot"}),
        observation=AgentObservation(
            "observation-1",
            "world-v1",
            {"inventory": {"raw_iron": 4}, "nearby": ["stone", "furnace"]},
        ),
        memory=AgentMemoryContext("verified memory", "memory-v1"),
        skills=(_skill(),),
        prior_actions=tuple(
            {"action_id": f"old-{index}", "payload": {"value": "x" * 96}}
            for index in range(16)
        ),
    )

    assert compiled.schema_version == "agent-prompt.v2"
    assert len(compiled.text) <= 1200
    assert all(f"[{block_id}]" in compiled.text for block_id in (
        "system", "goal", "observation", "skills",
    ))
    assert compiled.truncated_block_ids == ()
    assert compiled.compacted_block_ids == ("prior_actions",)
    assert compiled.history_projection is not None
    assert compiled.history_projection.compacted
    history_text = compiled.text.split("[prior_actions]\n", 1)[1].strip()
    history = json.loads(history_text)
    assert history["included_count"] == compiled.history_projection.included_count
    assert all("action_id" in row for row in history["actions"])


def test_agent_prompt_assembler_fails_closed_when_required_host_facts_do_not_fit() -> None:
    with pytest.raises(AgentPromptBudgetExceeded, match="no required fact was truncated"):
        AgentPromptAssembler(max_chars=512).compile(
            goal=AgentGoal("goal-1", "collect iron", {"target": "iron_ingot"}),
            observation=AgentObservation(
                "observation-1",
                "world-v1",
                {"nearby": ["x" * 4000]},
            ),
            memory=AgentMemoryContext("verified memory", "memory-v1"),
            skills=(_skill(),),
        )


def test_optional_prompt_blocks_are_whole_or_omitted() -> None:
    compiled = AgentPromptAssembler(max_chars=700).compile(
        goal=AgentGoal("goal-1", "collect iron", {}),
        observation=AgentObservation("observation-1", "world-v1", {"inventory": {}}),
        memory=AgentMemoryContext("memory", "memory-v1"),
        skills=(_skill(),),
        extra=(PromptBlock("large_optional", "z" * 1000, 60),),
    )

    assert "large_optional" in compiled.omitted_block_ids
    assert "[large_optional]" not in compiled.text
    assert compiled.truncated_block_ids == ()
