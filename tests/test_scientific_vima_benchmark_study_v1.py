from __future__ import annotations

from research.benchmarks.vima_bench import (
    VIMA_NOVEL_TASKS,
    VIMA_PARTITION_TASKS,
)
from research.reproductions.vima_embodied.benchmark import (
    build_vima_icml2023_benchmark,
)
from research.reproductions.vima_embodied.study import (
    build_vima_icml2023_study,
    vima_icml2023_trial_protocol,
)


def test_vima_bench_cut_preserves_camera_ready_partition_topology() -> None:
    benchmark = build_vima_icml2023_benchmark()
    assert len(benchmark.tasks) == 43
    assert len(benchmark.selected_tasks("placement_generalization")) == 13
    assert len(benchmark.selected_tasks("combinatorial_generalization")) == 13
    assert len(benchmark.selected_tasks("novel_object_generalization")) == 13
    novel = benchmark.selected_tasks("novel_task_generalization")
    assert len(novel) == 4
    assert {
        task.task_id.rsplit(":", 1)[-1] for task in novel
    } == set(VIMA_NOVEL_TASKS)
    assert set(VIMA_PARTITION_TASKS) == {
        "placement_generalization",
        "combinatorial_generalization",
        "novel_object_generalization",
        "novel_task_generalization",
    }


def test_vima_study_binds_method_cut_and_binary_success_protocol() -> None:
    benchmark = build_vima_icml2023_benchmark()
    protocol = vima_icml2023_trial_protocol(benchmark)
    definition = build_vima_icml2023_study(benchmark)

    assert protocol.protocol_id == "vima.icml2023.camera-ready.v1"
    assert definition.benchmark_split_id == "all"
    assert (
        definition.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    names = {
        row.measurement_id
        for row in definition.measurement_protocol.definitions
    }
    assert {
        "episode_success",
        "episode_steps",
        "partition_success_rate",
    } == names
