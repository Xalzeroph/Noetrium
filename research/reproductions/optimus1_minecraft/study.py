from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.minecraft_long_horizon_67 import (
    MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
    MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
    MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS,
    MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
    MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
)

from .program import OPTIMUS1_METHOD_PROGRAM
from .source import OPTIMUS1_PAPER_ERA_COMMIT


def optimus1_neurips2024_long_horizon_trial_protocol(
    benchmark,
):
    if benchmark.benchmark_id != MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID:
        raise ValueError("Optimus-1 study requires Minecraft Long-Horizon 67")
    selected = benchmark.selected_tasks(MINECRAFT_LONG_HORIZON_67_ALL_SPLIT)
    if len(selected) != MINECRAFT_LONG_HORIZON_67_TASK_COUNT:
        raise ValueError("Optimus-1 study requires the 67-task paper cut")
    return _rs.study_protocol(
        "optimus1.neurips2024.minecraft-long-horizon-67.v1",
        _rs.canonical_digest(
            {
                "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
                "method_program_digest": OPTIMUS1_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "benchmark_protocol_digest": (
                    MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST
                ),
                "benchmark_split_id": MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
                "task_ids": tuple(row.task_id for row in selected),
                "group_max_environment_steps": (
                    MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS
                ),
                "initial_inventory": (),
                "minecraft_version": "1.16.5",
                "environment_fps": 20,
                "controller": "steve1",
                "planner_release_binding": "gpt-4o",
                "paper_main_model_identity": "unresolved",
            }
        ),
    )


@_rs.study_factory('benchmark')
def build_optimus1_neurips2024_long_horizon_study(
    benchmark,
):
    protocol = optimus1_neurips2024_long_horizon_trial_protocol(benchmark)
    return _rs.study_spec(project_id="optimus1-neurips-2024-reproduction",
        study_id="optimus1-neurips-2024-minecraft-long-horizon-67",
        benchmark=benchmark,
        benchmark_split_id=MINECRAFT_LONG_HORIZON_67_ALL_SPLIT,
        method=_rs.study_participant(
            role="hybrid_multimodal_minecraft_agent",
            kind="agent_method",
            implementation="optimus1",
            treatment="neurips-2024-paper-era-release",
            capabilities=(
                "environment.minecraft",
                "model.multimodal.generate",
                "memory.retrieval",
            ),
            configurations=(
                "optimus1.hdkg",
                "optimus1.amep",
                "optimus1.knowledge-guided-planner",
                "optimus1.experience-driven-reflector",
                "optimus1.steve1-controller",
            ),
        ),
        models={
            "planner": _rs.study_model(
                "model.openai.gpt-4o-paper-era-release",
                prompt="optimus1.planner.paper-era",
            ),
            "controller": _rs.study_model(
                "model.steve1.paper-era-checkpoint",
                prompt="optimus1.controller.goal-conditioned",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "task_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="minecraft_goal_success",
                scale="binary",
                domain="minecraft_long_horizon_67",
            ),
            _rs.scalar_measurement(
                "environment_steps",
                schema_id="noetrium.measurement.count.v1",
                unit="environment_step",
                semantic_kind="minecraft_episode_length",
                scale="count",
                domain="minecraft_long_horizon_67",
            ),
            _rs.scalar_measurement(
                "wall_time_seconds",
                schema_id="noetrium.measurement.duration.v1",
                unit="second",
                semantic_kind="task_completion_wall_time",
                scale="continuous",
                domain="minecraft_long_horizon_67",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-world-seed-unpublished",),
        limits=_rs.trial_budget(
            "optimus1-neurips2024-long-horizon-67-safety",
            max_steps=36000,
            max_turns=4096,
            max_model_calls=2048,
            max_working_seconds=1800.0,
        ),
        replay_level='observational',
        repetition_timeout_seconds=1800.0,
    )


__all__ = [
    "build_optimus1_neurips2024_long_horizon_study",
    "optimus1_neurips2024_long_horizon_trial_protocol",
]
