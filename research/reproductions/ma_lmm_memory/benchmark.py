from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.lvu import (
    LVU_BENCHMARK_ID,
    LVUVideoRecord,
    MA_LMM_LVU_PROTOCOL,
    bind_lvu_cut,
)


MA_LMM_LVU_TEST_SPLIT = "test"
MA_LMM_LVU_SELECTION_DIGEST = canonical_digest({
    "benchmark_id": LVU_BENCHMARK_ID,
    "protocol_digest": MA_LMM_LVU_PROTOCOL.protocol_digest,
    "paper_usage": "ma-lmm-cvpr-2024",
})


def build_ma_lmm_lvu_cut(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    resolution = bind_lvu_cut(
        records,
        dataset_content_sha256=dataset_content_sha256,
        protocol=MA_LMM_LVU_PROTOCOL,
    )
    task_set = resolution.task_set
    selected = task_set.selected_tasks(MA_LMM_LVU_TEST_SPLIT)
    if not selected:
        raise ValueError("MA-LMM LVU cut requires non-empty test split")
    expected_families = {
        f"lvu_{task}" for task in MA_LMM_LVU_PROTOCOL.task_ids
    }
    present_families = {task.family for task in selected}
    missing = expected_families - present_families
    if missing:
        raise ValueError(
            "MA-LMM LVU cut is missing test task families: "
            f"{tuple(sorted(missing))}"
        )
    return task_set


__all__ = [
    "MA_LMM_LVU_SELECTION_DIGEST",
    "MA_LMM_LVU_TEST_SPLIT",
    "build_ma_lmm_lvu_cut",
]
