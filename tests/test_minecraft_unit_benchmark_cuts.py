"""Paper-grounded Minecraft benchmark protocols use the single native Unit."""
from __future__ import annotations

from research.benchmarks.deps_minecraft import (
    DEPS_ALL_SPLIT,
    DEPS_TASK_COUNT,
    bind_deps_minecraft_70_cut,
    build_deps_minecraft_70_cut,
)
from research.benchmarks.voyager_minecraft import (
    VOYAGER_MINECRAFT_LIFELONG_SPLIT,
    VOYAGER_MINECRAFT_TRIAL_COUNT,
    bind_voyager_minecraft_lifelong_cut,
    build_voyager_minecraft_lifelong_cut,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    benchmark_selected_tasks, benchmark_splits, task_content, task_id,
)


def test_deps_70_unit_cut_has_exact_source_and_diamond_objective():
    binding = bind_deps_minecraft_70_cut()
    cut = build_deps_minecraft_70_cut()
    assert binding.task_set is cut
    assert binding.source.unit_id == cut.unit_id
    tasks = benchmark_selected_tasks(cut, DEPS_ALL_SPLIT)
    assert len(tasks) == DEPS_TASK_COUNT == 70
    assert len({task_id(x) for x in tasks}) == 70
    diamonds = [x for x in tasks if task_id(x) == 'deps-minecraft:obtain_diamond']
    assert len(diamonds) == 1
    assert task_content(diamonds[0])['target_object'] == 'diamond'
    assert task_content(diamonds[0])['episode_step_ceiling'] == 12000
    assert len(benchmark_splits(cut)) == 9
    assert binding.source.parameters['content_digest'] == cut.parameters['source_digest']


def test_voyager_three_long_horizon_trials_use_native_unit():
    binding = bind_voyager_minecraft_lifelong_cut()
    cut = build_voyager_minecraft_lifelong_cut()
    assert binding.task_set is cut
    tasks = benchmark_selected_tasks(cut, VOYAGER_MINECRAFT_LIFELONG_SPLIT)
    assert len(tasks) == VOYAGER_MINECRAFT_TRIAL_COUNT == 3
    assert [task_content(x)['trial_index'] for x in tasks] == [1, 2, 3]
    assert all(task_content(x)['fresh_world'] is True for x in tasks)
    assert len(benchmark_splits(cut)) == 2


def test_benchmark_binding_repetition_does_not_recompile_unit_graph():
    first = build_deps_minecraft_70_cut()
    second = build_deps_minecraft_70_cut()
    assert first is second
    voyager = build_voyager_minecraft_lifelong_cut()
    assert voyager is build_voyager_minecraft_lifelong_cut()
    assert len(benchmark_selected_tasks(first)) == 70
    assert len(benchmark_selected_tasks(voyager)) == 3
