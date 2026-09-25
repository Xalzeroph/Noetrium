from __future__ import annotations

import hashlib

import pytest

from research.benchmarks.srdd import (
    SRDD_BENCHMARK_ID,
    SRDD_DATASET_COMMIT,
    SRDD_DATASET_GIT_BLOB_SHA1,
    SRDD_LICENSE,
    SRDD_SOURCE_CONTENT_DIGEST,
    SRDD_SPLIT_ID,
    SRDD_SUBCATEGORY_COUNT,
    SRDD_TASKS_PER_SUBCATEGORY,
    SRDD_TASK_COUNT,
    SrddTaskRecord,
    build_srdd_source,
    build_srdd_task_set,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _records() -> tuple[SrddTaskRecord, ...]:
    return tuple(
        SrddTaskRecord(
            index=index,
            software_name=f"Software_{index:04d}",
            category=f"Category_{index // SRDD_TASKS_PER_SUBCATEGORY:02d}",
            content_digest=_digest(
                f"Software_{index:04d}:"
                f"Category_{index // SRDD_TASKS_PER_SUBCATEGORY:02d}"
            ),
        )
        for index in range(SRDD_TASK_COUNT)
    )


def test_srdd_source_freezes_official_dataset_lane() -> None:
    source = build_srdd_source()
    assert source.source_id == SRDD_BENCHMARK_ID
    assert SRDD_DATASET_COMMIT in source.revision_id
    assert SRDD_DATASET_GIT_BLOB_SHA1 in source.revision_id
    assert source.content_digest == SRDD_SOURCE_CONTENT_DIGEST
    assert source.license == SRDD_LICENSE
    assert source.metadata["task_count"] == "1200"
    assert source.metadata["subcategory_count"] == "40"
    assert source.metadata["tasks_per_subcategory"] == "30"


def test_srdd_cut_is_exactly_1200_tasks_across_40_subcategories() -> None:
    cut = build_srdd_task_set(_records())
    assert cut.benchmark_id == SRDD_BENCHMARK_ID
    selected = cut.selected_tasks(SRDD_SPLIT_ID)
    assert len(selected) == SRDD_TASK_COUNT == 1200
    assert selected[0].task_id == "srdd:0000"
    assert selected[-1].task_id == "srdd:1199"

    category_splits = tuple(
        split
        for split in cut.splits
        if split.split_id.startswith("category:")
    )
    assert len(category_splits) == SRDD_SUBCATEGORY_COUNT == 40
    assert all(
        len(cut.selected_tasks(split.split_id))
        == SRDD_TASKS_PER_SUBCATEGORY
        for split in category_splits
    )
    assert all(
        task.package.verifier_requirement_id
        == "benchmark.srdd.chatdev-paper-metrics.verifier"
        for task in selected
    )
    assert all(
        task.package.environment_requirement_id
        == "benchmark.srdd.software-repository"
        for task in selected
    )


def test_srdd_cut_rejects_incomplete_or_unbalanced_data() -> None:
    with pytest.raises(ValueError, match="exactly 1200"):
        build_srdd_task_set(_records()[:-1])

    records = list(_records())
    records[-1] = SrddTaskRecord(
        index=records[-1].index,
        software_name=records[-1].software_name,
        category="Category_00",
        content_digest=records[-1].content_digest,
    )
    with pytest.raises(ValueError, match="exactly 30"):
        build_srdd_task_set(tuple(records))
