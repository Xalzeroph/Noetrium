from __future__ import annotations

from noetrium_platform.capabilities.participant.agent.api import (
    AgentGoal,
    AgentObservation,
    AgentStepReceipt,
)
from noetrium_platform.capabilities.participant.agent.runtime import MachineAgentMemory
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
)
from noetrium_platform.research.execution.machines import MemoryPresetSpec


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run",
        "trace",
        "span",
        participant_generations=(("environment", "world-v1"),),
    )


def _receipt(index: int, *, verified: bool | None = True) -> AgentStepReceipt:
    return AgentStepReceipt(
        f"action:{index}",
        "move",
        "skill.move",
        f"sequence:{index}",
        True,
        verified,
        effect_certainty="confirmed" if verified else "rejected",
    )


def test_memory_machine_reopens_from_journal_without_domain_checkpoint() -> None:
    journal = InMemoryMachineJournal()
    first = MachineAgentMemory.create_default("agent-a", journal=journal)
    first.record(_receipt(1), _context())
    first.record(_receipt(2), _context())
    first_cut = first.cut()
    assert first_cut is not None

    restored = MachineAgentMemory.create_default("agent-a", journal=journal)
    assert [record.record_id for record in restored.records] == [
        "memory:episode:action:1",
        "memory:episode:action:2",
    ]
    assert restored.cut() == first_cut

    restored.record(_receipt(3), _context())
    assert [record.record_id for record in restored.records] == [
        "memory:episode:action:1",
        "memory:episode:action:2",
        "memory:episode:action:3",
    ]
    assert restored.cut() is not None
    assert restored.cut().revision > first_cut.revision


def test_verified_read_firewall_is_program_semantics() -> None:
    memory = MachineAgentMemory.create_default("agent-b")
    memory.record(_receipt(1, verified=False), _context())
    goal = AgentGoal("goal", "move safely", {})
    observation = AgentObservation("obs", "world-v1", {"task": "move"})

    empty = memory.recall(goal, observation, _context())
    assert empty.context_text == ""

    memory.verify("memory:episode:action:1", verified=True)
    recalled = memory.recall(goal, observation, _context())
    assert "action=move" in recalled.context_text
    assert recalled.query_id.startswith("memory-query:")


def test_default_retention_policy_is_bounded_but_replaceable() -> None:
    memory = MachineAgentMemory.create_default(
        "agent-c",
        preset=MemoryPresetSpec(max_records=2, recall_limit=2),
    )
    memory.record(_receipt(1), _context())
    memory.record(_receipt(2), _context())
    memory.record(_receipt(3), _context())

    assert [record.record_id for record in memory.records] == [
        "memory:episode:action:2",
        "memory:episode:action:3",
    ]


def test_no_domain_checkpoint_surface_remains_on_machine_memory() -> None:
    memory = MachineAgentMemory.create_default("agent-d")
    assert not hasattr(memory, "checkpoint")
    assert not hasattr(memory, "restore")
