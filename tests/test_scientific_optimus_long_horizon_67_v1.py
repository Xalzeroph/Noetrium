from __future__ import annotations

from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
    MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS,
    MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS,
    MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS,
    MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
    MINECRAFT_LONG_HORIZON_67_TASKS,
    build_minecraft_long_horizon_67_cut,
)
from research.reproductions.optimus1_minecraft.study import (
    build_optimus1_neurips2024_long_horizon_study,
    optimus1_neurips2024_long_horizon_trial_protocol,
)
from research.reproductions.optimus2_minecraft.study import (
    build_optimus2_cvpr2025_long_horizon_study,
    optimus2_cvpr2025_long_horizon_trial_protocol,
)


def test_minecraft_long_horizon_67_recovers_paper_cut_from_release() -> None:
    benchmark = build_minecraft_long_horizon_67_cut()

    assert len(benchmark.selected_tasks(MINECRAFT_LONG_HORIZON_67_ALL_SPLIT)) == 67
    assert MINECRAFT_LONG_HORIZON_67_TASK_COUNT == 67
    assert MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS == (
        ("wooden", 10),
        ("stone", 9),
        ("iron", 16),
        ("golden", 6),
        ("redstone", 6),
        ("diamond", 7),
        ("armor", 13),
    )
    assert MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS == (
        ("wooden", 3600),
        ("stone", 7200),
        ("iron", 12000),
        ("golden", 36000),
        ("redstone", 36000),
        ("diamond", 36000),
        ("armor", 36000),
    )
    assert len(MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS) == 6
    assert {
        instruction.lower()
        for _, _, instruction in MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS
    } == {
        "chop a tree",
        "dig down to mine dirt",
        "dig down to mine cobblestone",
        "dig down to mine iron ore",
        "dig down to mine gold ore",
        "dig down to mine redstone",
    }
    assert any(
        row.group == "diamond"
        and row.instruction == "Dig down and mine a diamond"
        for row in MINECRAFT_LONG_HORIZON_67_TASKS
    )
    for group, count in MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS:
        assert len(benchmark.selected_tasks(f"group:{group}")) == count


def test_optimus1_and_optimus2_share_exact_long_horizon_cut() -> None:
    benchmark = build_minecraft_long_horizon_67_cut()
    p1 = optimus1_neurips2024_long_horizon_trial_protocol(benchmark)
    p2 = optimus2_cvpr2025_long_horizon_trial_protocol(benchmark)
    s1 = build_optimus1_neurips2024_long_horizon_study(benchmark)
    s2 = build_optimus2_cvpr2025_long_horizon_study(benchmark)

    assert p1.protocol_id == (
        "optimus1.neurips2024.minecraft-long-horizon-67.v1"
    )
    assert p2.protocol_id == (
        "optimus2.cvpr2025.minecraft-long-horizon-67.v1"
    )
    assert s1.trial_protocol_identity == p1
    assert s2.trial_protocol_identity == p2
    assert s1.benchmark is benchmark
    assert s2.benchmark is benchmark
    assert s1.benchmark.cut_digest == s2.benchmark.cut_digest
    assert {
        row.measurement_id for row in s1.measurement_protocol.definitions
    } == {"environment_steps", "task_success", "wall_time_seconds"}
    assert {
        row.measurement_id for row in s2.measurement_protocol.definitions
    } == {"environment_steps", "task_success"}
