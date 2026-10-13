from __future__ import annotations

from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
    MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT,
    bind_minecraft_long_horizon_67_cut,
    build_minecraft_long_horizon_67_cut,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_package as unit_task_package
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    benchmark_selected_tasks,
    benchmark_splits,
    task_content,
    task_family,
    task_id,
)


def test_minecraft_long_horizon_paper_cut_is_one_native_unit_with_67_grounded_tasks():
    bound = bind_minecraft_long_horizon_67_cut()
    unit = bound.task_set
    assert unit is build_minecraft_long_horizon_67_cut()
    assert unit.has_trait("research.benchmark")
    assert unit.unit_id == "minecraft-long-horizon-67"
    assert bound.source.parameters["content_digest"] == MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST
    assert bound.source.parameters["metadata"]["source_commit"] == MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT
    tasks = benchmark_selected_tasks(unit, "all")
    assert len(tasks) == 67
    assert len({task_id(row) for row in tasks}) == 67
    diamond = [row for row in tasks if task_family(row).endswith("_diamond")]
    assert len(diamond) == 7
    assert any("mine a diamond" in task_content(row)["objective"].lower() for row in diamond)
    assert len(benchmark_splits(unit)) == 8
    for row in tasks:
        payload = task_content(row)
        assert payload["objective"] == payload["instruction"]
        assert unit_task_package(row)["verifier_isolation"] == "separate"


def test_optimus_reproduction_benchmarks_share_the_frozen_single_unit():
    from research.reproductions.optimus1_minecraft.benchmark import build_optimus1_long_horizon_67_cut
    from research.reproductions.optimus2_minecraft.benchmark import build_optimus2_long_horizon_67_cut

    first = build_optimus1_long_horizon_67_cut()
    second = build_optimus2_long_horizon_67_cut()
    assert first is second
    assert first.unit_digest == build_minecraft_long_horizon_67_cut().unit_digest
