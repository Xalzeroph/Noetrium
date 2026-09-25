from __future__ import annotations

import pytest

from research.reproductions.memgpt_classic import (
    MEMGPT_CLASSIC_FIDELITY,
    MemGPTCoreMemory,
    MemGPTMemoryQuery,
    MemGPTMemoryTier,
    classic_summary_partition,
)


def test_memgpt_classic_fidelity_pins_paper_era_paging() -> None:
    fidelity = MEMGPT_CLASSIC_FIDELITY
    assert fidelity.audited_anchor_commit == "15540c24ac328c995fb11f89d2e228cde508ab37"
    assert fidelity.core_memory_in_context is True
    assert fidelity.core_memory_edit_rebuilds_prompt is True
    assert fidelity.recall_memory_external is True
    assert fidelity.archival_memory_external is True
    assert fidelity.recall_default_page_size == 5
    assert fidelity.archival_default_page_size == 5
    assert fidelity.overflow_strategy == "summarize_then_retry_same_step"
    assert fidelity.preserve_system_message_during_summary is True


def test_memgpt_memory_query_uses_fixed_page_offset() -> None:
    query = MemGPTMemoryQuery(MemGPTMemoryTier.ARCHIVAL, "database migration", page=3, count=5)
    assert query.start == 15
    recall = MemGPTMemoryQuery(MemGPTMemoryTier.RECALL, "previous answer", page=2, count=7)
    assert recall.start == 14
    with pytest.raises(ValueError, match="core memory"):
        MemGPTMemoryQuery(MemGPTMemoryTier.CORE, "not paged")


def test_memgpt_core_memory_is_method_owned_editable_state() -> None:
    memory = MemGPTCoreMemory({"human": "name: Alice", "persona": "helpful"})
    updated = memory.replace("human", "Alice", "Bob")
    assert memory.blocks["human"] == "name: Alice"
    assert updated.blocks["human"] == "name: Bob"
    appended = updated.append("human", "likes graphs")
    assert appended.blocks["human"] == "name: Bob\nlikes graphs"


def test_memgpt_overflow_partition_preserves_system_and_host_truth() -> None:
    source = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a3"},
        {"role": "user", "content": "u3"},
    ]
    original = [dict(row) for row in source]
    partition = classic_summary_partition(source)

    assert source == original
    assert all(row["content"] != "system" for row in partition.summarize)
    assert partition.summarize == (
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    )
    assert partition.retain[0] == {"role": "assistant", "content": "a2"}


def test_memgpt_user_cutoff_moves_forward_once() -> None:
    messages = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    partition = classic_summary_partition(messages, cutoff=2)
    assert partition.cutoff == 3
    assert partition.summarize[-1] == {"role": "user", "content": "u1"}
    assert partition.retain == ({"role": "assistant", "content": "a1"},)
