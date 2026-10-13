from __future__ import annotations
from research.benchmarks.ego4d_goalstep import (
    EGO4D_GOALSTEP_BENCHMARK_ID,
    Ego4DGoalStepVideoRecord,
    bind_ego4d_goalstep_cut,
)


def build_providellm_goalstep_cut(
    records: tuple[Ego4DGoalStepVideoRecord, ...],
    *,
    dataset_content_sha256: str,
):
    task_set = bind_ego4d_goalstep_cut(
        records,
        dataset_content_sha256=dataset_content_sha256,
    ).task_set
    if task_set.benchmark_id != EGO4D_GOALSTEP_BENCHMARK_ID:
        raise ValueError("ProVideLLM GoalStep benchmark authority drifted")
    if not task_set.selected_tasks("val"):
        raise ValueError("ProVideLLM GoalStep cut requires validation tasks")
    return task_set


__all__ = ["build_providellm_goalstep_cut"]
