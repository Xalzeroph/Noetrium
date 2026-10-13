from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_TASK_SETUP_SCHEMA_V2,
    MINECRAFT_TASK_SUCCESS_KINDS,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    benchmark_selected_tasks,
    task_content,
    task_unit_package,
)
from research.benchmarks.mineevolve_long_horizon_70 import build_native_cut


def _assert_native_task(task):
    content = task_content(task)
    minecraft = content["environment_setup"]["minecraft"]
    assert minecraft["schema"] == MINECRAFT_TASK_SETUP_SCHEMA_V2
    assert "scenario" not in minecraft
    assert "verification_command" not in repr(content)
    assert content["success"]["kind"] in MINECRAFT_TASK_SUCCESS_KINDS
    assert task_unit_package(task)["environment_requirement_id"] == "environment.minecraft"


def test_mineevolve_native_cut_preserves_all_official_task_identities():
    cut = build_native_cut()
    tasks = benchmark_selected_tasks(cut, "all")
    assert len(tasks) == 70
    assert len(benchmark_selected_tasks(cut, "ablation-balanced-28")) == 28
    for task in tasks:
        _assert_native_task(task)
        assert "official_evaluator" in task_content(task)
