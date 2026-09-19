from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet
from research.benchmarks.lvu import (
    LVU_BENCHMARK_ID,
    LVUFullVideoProtocol,
    LVUVideoRecord,
    MA_LMM_LVU_TASKS,
    bind_lvu_full_video_cut,
)


ADACM2_LVU_TEST_SPLIT = "test"
ADACM2_LVU_PROTOCOL = LVUFullVideoProtocol(
    task_ids=MA_LMM_LVU_TASKS,
    fps=10,
)


def build_adacm2_lvu_cut(
    records: tuple[LVUVideoRecord, ...],
    *,
    dataset_content_sha256: str,
) -> BenchmarkTaskSet:
    resolution = bind_lvu_full_video_cut(
        records,
        dataset_content_sha256=dataset_content_sha256,
        protocol=ADACM2_LVU_PROTOCOL,
    )
    task_set = resolution.task_set
    if task_set.benchmark_id != LVU_BENCHMARK_ID:
        raise ValueError("AdaCM2 LVU benchmark authority drifted")
    selected = task_set.selected_tasks(ADACM2_LVU_TEST_SPLIT)
    if not selected:
        raise ValueError("AdaCM2 LVU test split must be non-empty")
    expected_families = {
        f"lvu_{task}" for task in ADACM2_LVU_PROTOCOL.task_ids
    }
    present_families = {task.family for task in selected}
    missing = expected_families - present_families
    if missing:
        raise ValueError(
            "AdaCM2 LVU cut is missing test task families: "
            f"{tuple(sorted(missing))}"
        )
    if any(
        "projection:full-video-stream" not in task.lineage_refs
        for task in selected
    ):
        raise ValueError(
            "AdaCM2 LVU tasks must use full-video stream projection"
        )
    return task_set


__all__ = [
    "ADACM2_LVU_PROTOCOL",
    "ADACM2_LVU_TEST_SPLIT",
    "build_adacm2_lvu_cut",
]
