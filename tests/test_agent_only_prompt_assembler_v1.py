import json

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
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
    AgentContextBudgetExceeded,
    AgentContextCompiler,
    default_agent_context_program,
    default_agent_context_renderers,
)
from noetrium_platform.research.execution.machines import (
    ContextBlockProgram,
    ContextProgram,
    ContextRenderResult,
)


def _skill() -> AgentSkillDescription:
    return AgentSkillDescription(
        "collect_block",
        "minecraft",
        "collect one block",
        '{"block":"string","count":"int"}',
        True,
    )


def _inputs():
    return dict(
        goal=AgentGoal("goal-1", "collect iron", {"target": "iron_ingot"}),
        observation=AgentObservation(
            "observation-1",
            "world-v1",
            {"inventory": {"raw_iron": 4}, "nearby": ["stone", "furnace"]},
        ),
        memory=AgentMemoryContext("verified memory", "memory-v1"),
        skills=(_skill(),),
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


def test_agent_context_program_compacts_history_without_mutating_host_facts() -> None:
    compiled = AgentContextCompiler(max_chars=1200).compile(
        **_inputs(),
        prior_actions=tuple(
            {"action_id": f"old-{index}", "payload": {"value": "x" * 96}}
            for index in range(16)
        ),
    )

    assert compiled.schema_version == "agent-context.v4"
    assert len(compiled.context_binding_digest) == 64
    assert len(compiled.text) <= 1200
    assert all(f"[{block_id}]" in compiled.text for block_id in (
        "system", "goal", "observation", "skills",
    ))
    assert compiled.compacted_block_ids == ("prior_actions",)
    assert compiled.history_projection is not None
    assert compiled.history_projection.compacted
    history_text = compiled.text.split("[prior_actions]\n", 1)[1].strip()
    history = json.loads(history_text)
    assert history["included_count"] == compiled.history_projection.included_count


def test_agent_context_program_fails_closed_when_required_facts_do_not_fit() -> None:
    values = _inputs()
    values["observation"] = AgentObservation(
        "observation-1",
        "world-v1",
        {"nearby": ["x" * 4000]},
    )
    with pytest.raises(AgentContextBudgetExceeded, match="required context facts exceed"):
        AgentContextCompiler(max_chars=512).compile(**values)


def test_downstream_can_replace_context_program_and_renderer_without_platform_change() -> None:
    base = default_agent_context_program(max_chars=800)
    custom = ContextProgram(
        program_id="paper.custom-context",
        version="1",
        max_chars=800,
        blocks=(
            ContextBlockProgram(
                "paper_instruction",
                "paper.instruction",
                priority=120,
                required=True,
            ),
            *tuple(block for block in base.blocks if block.block_id != "system"),
            ContextBlockProgram(
                "large_optional",
                "paper.large",
                priority=60,
            ),
        ),
    )
    renderers = default_agent_context_renderers()
    renderers.register(
        "paper.instruction",
        lambda request: ContextRenderResult("Use the paper-specific execution policy."),
        implementation_digest=canonical_digest({
            "renderer": "paper.instruction",
            "implementation_revision": 1,
        }),
    )
    renderers.register(
        "paper.large",
        lambda request: ContextRenderResult("z" * 1000),
        implementation_digest=canonical_digest({
            "renderer": "paper.large",
            "implementation_revision": 1,
        }),
    )

    compiled = AgentContextCompiler(
        program=custom,
        renderers=renderers,
    ).compile(**_inputs())

    assert compiled.context_program_digest == custom.program_digest
    assert "[paper_instruction]" in compiled.text
    assert "[system]" not in compiled.text
    assert "large_optional" in compiled.omitted_block_ids
    assert "[large_optional]" not in compiled.text
