"""Canonical VIMA-Bench camera-ready evaluation authority."""

from .cut import (
    VIMA_BENCHMARK_ID,
    VIMA_BENCHMARK_REPOSITORY,
    VIMA_BENCH_PAPER_COMMIT,
    VIMA_CAMERA_READY_EXECUTABLE_SEED,
    VIMA_NOVEL_TASKS,
    VIMA_PARTITION_TASKS,
    VIMA_PROTOCOL_DIGEST,
    VIMA_TASK_SCHEMA_ID,
    VIMA_TRAINED_TASKS,
    bind_vima_bench_camera_ready_cut,
    build_vima_bench_camera_ready_cut,
    build_vima_bench_source,
    vima_bench_revision,
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
