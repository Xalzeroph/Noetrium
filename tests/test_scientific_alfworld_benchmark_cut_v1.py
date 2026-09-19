from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import BenchmarkSourceKind
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_DATASET_PATH,
    ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT,
    ALFWORLD_PAPER_EVAL_REVISION,
    ALFWORLD_PAPER_EVAL_SPLIT,
    ALFWORLD_TASK_FAMILIES,
    AlfworldTaskRecord,
    bind_alfworld_paper_eval_cut,
    build_alfworld_paper_eval_task_set,
)


def _records(count: int = ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT) -> tuple[AlfworldTaskRecord, ...]:
    return tuple(
        AlfworldTaskRecord(
            gamefile=f"{ALFWORLD_TASK_FAMILIES[index % len(ALFWORLD_TASK_FAMILIES)]}/scene-{index:03d}/game.tw-pddl",
            family=ALFWORLD_TASK_FAMILIES[index % len(ALFWORLD_TASK_FAMILIES)],
            content_digest=canonical_digest({"task": index}),
        )
        for index in range(count)
    )


def test_alfworld_paper_cut_binds_existing_study_benchmark_abi() -> None:
    records = _records()
    source_digest = canonical_digest({"dataset": ALFWORLD_PAPER_EVAL_DATASET_PATH})

    resolution = bind_alfworld_paper_eval_cut(
        records,
        locator=f"/datasets/{ALFWORLD_PAPER_EVAL_DATASET_PATH}",
        source_digest=source_digest,
    )

    assert resolution.source.source_id == ALFWORLD_BENCHMARK_ID
    assert resolution.source.kind is BenchmarkSourceKind.LOCAL_FILE
    assert resolution.source.revision_id == ALFWORLD_PAPER_EVAL_REVISION
    assert resolution.source.content_digest == source_digest
    assert resolution.source.metadata["dataset_path"] == ALFWORLD_PAPER_EVAL_DATASET_PATH

    task_set = resolution.task_set
    assert task_set.benchmark_id == ALFWORLD_BENCHMARK_ID
    assert task_set.revision_id == ALFWORLD_PAPER_EVAL_REVISION
    assert len(task_set.tasks) == ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT
    assert tuple(task.task_id for task in task_set.tasks) == tuple(sorted(task.task_id for task in task_set.tasks))
    assert tuple(task.task_id for task in task_set.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)) == tuple(
        record.task_id for record in records
    )
    assert {task.family for task in task_set.tasks} == set(ALFWORLD_TASK_FAMILIES)


def test_alfworld_paper_cut_rejects_partial_task_set() -> None:
    with pytest.raises(ValueError, match="exactly 134 tasks"):
        build_alfworld_paper_eval_task_set(
            _records(ALFWORLD_PAPER_EVAL_EXPECTED_TASK_COUNT - 1),
            source_digest=canonical_digest({"dataset": "partial"}),
        )


def test_alfworld_task_identity_is_dataset_relative_and_stable() -> None:
    record = AlfworldTaskRecord(
        gamefile="pick_and_place/scene-a/game.tw-pddl",
        family="pick_and_place",
        content_digest=canonical_digest({"game": "a"}),
    )
    equivalent = AlfworldTaskRecord(
        gamefile="/pick_and_place/scene-a/game.tw-pddl/",
        family="pick_and_place",
        content_digest=record.content_digest,
    )

    assert record.task_id == equivalent.task_id == "alfworld:pick_and_place/scene-a/game.tw-pddl"
