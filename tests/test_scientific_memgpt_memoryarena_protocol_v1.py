from __future__ import annotations

from research.benchmarks.memoryarena import (
    MEMORYARENA_BENCHMARK_ID,
    MEMORYARENA_CODE_COMMIT,
    MemoryArenaTaskRecord,
    build_memoryarena_source,
    build_memoryarena_task_set,
)
from research.reproductions.memgpt_classic.program import MEMGPT_CLASSIC_METHOD_PROGRAM
from research.reproductions.memgpt_classic.study import (
    MEMGPT_MEMORYARENA_TRIAL_PROTOCOL,
    build_memgpt_memoryarena_study,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _benchmark():
    return build_memoryarena_task_set(
        (
            MemoryArenaTaskRecord(
                "math-001",
                "formal_reasoning_math",
                "test",
                SHA_B,
            ),
            MemoryArenaTaskRecord(
                "shop-001",
                "web_shopping",
                "test",
                SHA_C,
            ),
        ),
        dataset_revision="hf-dataset-revision-001",
        dataset_content_sha256=SHA_A,
    )


def test_memoryarena_adapter_freezes_code_dataset_tasks_and_split() -> None:
    source = build_memoryarena_source(
        dataset_revision="hf-dataset-revision-001",
        dataset_content_sha256=SHA_A,
    )
    benchmark = _benchmark()

    assert MEMORYARENA_CODE_COMMIT == "6cd9de14b71915e39ac742a20dc33785e14b6aab"
    assert benchmark.benchmark_id == MEMORYARENA_BENCHMARK_ID
    assert benchmark.revision_id == source.revision_id
    assert benchmark.source_digest == source.content_digest
    assert tuple(task.task_id for task in benchmark.selected_tasks("test")) == (
        "math-001",
        "shop-001",
    )
    assert all(task.package is not None for task in benchmark.tasks)
    assert len(benchmark.cut_digest) == 64


def test_memgpt_memoryarena_study_binds_method_benchmark_models_and_metrics() -> None:
    definition = build_memgpt_memoryarena_study(_benchmark(), split_id="test")

    assert definition.benchmark.benchmark_id == MEMORYARENA_BENCHMARK_ID
    assert definition.benchmark_split_id == "test"
    assert MEMGPT_CLASSIC_METHOD_PROGRAM.program_digest
    assert MEMGPT_MEMORYARENA_TRIAL_PROTOCOL.protocol_digest

    participant = definition.binding_requirements.participants[0]
    assert participant.method_id == "memgpt-classic"
    assert set(participant.capability_requirement_ids) == {
        "memory.recall.query",
        "memory.archival.query",
        "memory.archival.insert",
    }

    roles = {
        row.role: row
        for row in definition.binding_requirements.model_roles
    }
    assert set(roles) == {"agent", "summarizer"}

    measurement_ids = {
        row.measurement_id
        for row in definition.measurement_protocol.measurements
    }
    assert measurement_ids == {
        "task_success",
        "agent_turn_count",
        "memory_query_count",
        "memory_write_count",
        "summary_count",
    }
    assert definition.execution_policy.trial_budget.max_turns == 128
    assert definition.execution_policy.trial_budget.max_model_calls == 160
