from noetrium_platform.capabilities.participant.agent.api import (
    AgentGoal,
    AgentMemoryContext,
    AgentObservation,
    AgentSkillDescription,
)
from noetrium_platform.capabilities.participant.agent.runtime.prompt import (
    AgentPromptAssembler,
    PromptBlock,
)


def test_agent_prompt_assembler_preserves_required_boundaries_under_pressure():
    compiled = AgentPromptAssembler(max_chars=512).compile(
        goal=AgentGoal("goal-1", "collect iron", {"target": "iron_ingot"}),
        observation=AgentObservation(
            "observation-1",
            "world-v1",
            {"inventory": {"raw_iron": 64}, "nearby": ["x"] * 300},
        ),
        memory=AgentMemoryContext("verified " * 1000, "memory-v1"),
        skills=(
            AgentSkillDescription(
                "collect_block",
                "minecraft",
                "collect one block",
                '{"block":"string","count":"int"}',
                True,
            ),
        ),
        prior_actions=({"action": "old"},) * 100,
        extra=(PromptBlock("low_priority", "discard me " * 1000, 1),),
    )

    assert len(compiled.text) <= 512
    assert compiled.truncated is True
    assert all(f"[{block_id}]" in compiled.text for block_id in ("system", "goal", "observation", "skills"))
    assert "omitted middle context" in compiled.text
    assert "low_priority" not in compiled.block_ids
    assert "low_priority" in compiled.omitted_block_ids
    assert "observation" in compiled.truncated_block_ids or "memory" in compiled.truncated_block_ids
