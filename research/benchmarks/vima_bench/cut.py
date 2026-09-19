from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

VIMA_BENCHMARK_ID = "vima-bench"
VIMA_BENCHMARK_REPOSITORY = "https://github.com/vimalabs/VIMABench"
VIMA_BENCH_PAPER_COMMIT = "224c2d870d6063d90215201ba42d4211ddc957d7"
VIMA_TASK_SCHEMA_ID = "vima-bench.task-partition-cell.v1"
VIMA_CAMERA_READY_EXECUTABLE_SEED = 42

VIMA_NOVEL_TASKS = (
    "follow_motion",
    "novel_adj_and_noun",
    "same_texture",
    "sweep_without_touching",
)

VIMA_TRAINED_TASKS = (
    "follow_order",
    "manipulate_old_neighbor",
    "novel_adj",
    "novel_noun",
    "pick_in_order_then_restore",
    "rearrange",
    "rearrange_then_restore",
    "rotate",
    "same_shape",
    "scene_understanding",
    "sweep_without_exceeding",
    "twist",
    "visual_manipulation",
)

VIMA_PARTITION_TASKS = {
    "placement_generalization": VIMA_TRAINED_TASKS,
    "combinatorial_generalization": VIMA_TRAINED_TASKS,
    "novel_object_generalization": VIMA_TRAINED_TASKS,
    "novel_task_generalization": VIMA_NOVEL_TASKS,
}

VIMA_PROTOCOL_DIGEST = canonical_digest({
    "benchmark_commit": VIMA_BENCH_PAPER_COMMIT,
    "partition_tasks": VIMA_PARTITION_TASKS,
    "success_semantics": "binary-no-partial-reward",
    "final_metric": "mean-success-rate-over-evaluated-tasks",
    "camera_ready_executable_seed": VIMA_CAMERA_READY_EXECUTABLE_SEED,
    "episode_budget": "oracle-max-steps-plus-two",
})


def vima_bench_revision() -> str:
    return (
        f"icml2023@{VIMA_BENCH_PAPER_COMMIT}:"
        f"protocol:{VIMA_PROTOCOL_DIGEST}"
    )


def build_vima_bench_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=VIMA_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=vima_bench_revision(),
        locator=VIMA_BENCHMARK_REPOSITORY,
        content_digest=VIMA_PROTOCOL_DIGEST,
        metadata={
            "paper_venue": "ICML 2023",
            "task_count": "17",
            "evaluation_level_count": "4",
            "evaluated_task_partition_cells": "43",
            "success_criterion": "binary",
            "paper_episode_count": "not-content-addressed",
            "camera_ready_example_seed": str(
                VIMA_CAMERA_READY_EXECUTABLE_SEED
            ),
        },
    )


def build_vima_bench_camera_ready_cut() -> BenchmarkTaskSet:
    revision = vima_bench_revision()
    tasks: list[TaskDefinition] = []
    split_ids: dict[str, list[str]] = {
        partition: [] for partition in VIMA_PARTITION_TASKS
    }
    for partition in sorted(VIMA_PARTITION_TASKS):
        for task_name in VIMA_PARTITION_TASKS[partition]:
            task_id = f"vima-bench:{partition}:{task_name}"
            content_digest = canonical_digest({
                "benchmark_commit": VIMA_BENCH_PAPER_COMMIT,
                "partition": partition,
                "task_name": task_name,
                "seed": VIMA_CAMERA_READY_EXECUTABLE_SEED,
                "success": "binary-no-partial-reward",
                "episode_budget": "oracle-max-steps-plus-two",
            })
            tasks.append(
                TaskDefinition(
                    task_id=task_id,
                    revision_id=revision,
                    family=f"vima_{task_name}",
                    schema_id=VIMA_TASK_SCHEMA_ID,
                    content_digest=content_digest,
                    lineage_refs=(
                        f"partition:{partition}",
                        f"task:{task_name}",
                        "success:binary",
                        "episode-budget:oracle-max-steps-plus-two",
                        "camera-ready-example-seed:42",
                    ),
                    package=TaskPackageSpec(
                        package_schema_id=(
                            "vima-bench.multimodal-manipulation-cell.v1"
                        ),
                        instruction_digest=content_digest,
                        environment_requirement_id=(
                            "environment.embodied.vima-bench-camera-ready"
                        ),
                        verifier_requirement_id=(
                            "benchmark.vima-bench.binary-success"
                        ),
                        verifier_isolation=TaskVerifierIsolation.SEPARATE,
                    ),
                )
            )
            split_ids[partition].append(task_id)

    ordered = tuple(sorted(tasks, key=lambda row: row.task_id))
    all_ids = tuple(row.task_id for row in ordered)
    splits = [TaskSetSplit("all", all_ids)]
    for partition in sorted(split_ids):
        splits.append(
            TaskSetSplit(partition, tuple(sorted(split_ids[partition])))
        )
    return BenchmarkTaskSet(
        benchmark_id=VIMA_BENCHMARK_ID,
        revision_id=revision,
        source_digest=VIMA_PROTOCOL_DIGEST,
        task_schema_id=VIMA_TASK_SCHEMA_ID,
        tasks=ordered,
        splits=tuple(splits),
        selection_policy_digest=canonical_digest({
            "protocol_digest": VIMA_PROTOCOL_DIGEST,
            "task_ids": all_ids,
            "partition_tasks": VIMA_PARTITION_TASKS,
        }),
    )


def bind_vima_bench_camera_ready_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_vima_bench_source(),
        task_set=build_vima_bench_camera_ready_cut(),
    )


__all__ = [
    "VIMA_BENCHMARK_ID",
    "VIMA_BENCHMARK_REPOSITORY",
    "VIMA_BENCH_PAPER_COMMIT",
    "VIMA_CAMERA_READY_EXECUTABLE_SEED",
    "VIMA_NOVEL_TASKS",
    "VIMA_PARTITION_TASKS",
    "VIMA_PROTOCOL_DIGEST",
    "VIMA_TASK_SCHEMA_ID",
    "VIMA_TRAINED_TASKS",
    "bind_vima_bench_camera_ready_cut",
    "build_vima_bench_camera_ready_cut",
    "build_vima_bench_source",
    "vima_bench_revision",
]
