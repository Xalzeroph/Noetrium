from __future__ import annotations

from functools import lru_cache
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkSourceKind, BenchmarkSourceResolution, TaskVerifierIsolation,
    benchmark_source_unit, benchmark_cut_unit, task_unit, task_package,
    split_unit, task_id,
)

VOYAGER_MINECRAFT_BENCHMARK_ID = "voyager-minecraft"
VOYAGER_MINECRAFT_LIFELONG_SPLIT = "lifelong-learning"
VOYAGER_MINECRAFT_SOURCE_REPOSITORY = "https://github.com/MineDojo/Voyager"
VOYAGER_MINECRAFT_PAPER_COMMIT = "edeee8383a22b96b54bff51c6cf809306a7b34a3"
VOYAGER_MINECRAFT_TRIAL_COUNT = 3
VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS = 160
VOYAGER_MINECRAFT_TASK_SCHEMA_ID = "voyager.minecraft.open-world-lifelong-trial.v1"

VOYAGER_MINECRAFT_PROTOCOL_DIGEST = canonical_digest({
    "paper": "Voyager TMLR 2024",
    "source_repository": VOYAGER_MINECRAFT_SOURCE_REPOSITORY,
    "source_commit": VOYAGER_MINECRAFT_PAPER_COMMIT,
    "trial_count": VOYAGER_MINECRAFT_TRIAL_COUNT,
    "max_prompting_iterations": VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
    "world_semantics": "independent-fresh-minecraft-world-per-trial",
    "task_reset_semantics": "reset-rejoin-after-each-curriculum-task",
    "metrics": (
        "unique_item_count",
        "wooden_tool_unlock_iteration",
        "stone_tool_unlock_iteration",
        "iron_tool_unlock_iteration",
        "diamond_tool_unlock_iteration",
        "travel_distance_blocks",
    ),
})


def voyager_minecraft_revision() -> str:
    return (
        f"tmlr2024@{VOYAGER_MINECRAFT_PAPER_COMMIT}:"
        f"protocol:{VOYAGER_MINECRAFT_PROTOCOL_DIGEST}"
    )


@lru_cache(maxsize=1)
def build_voyager_minecraft_source() -> NoetriumUnit:
    return benchmark_source_unit(
        VOYAGER_MINECRAFT_BENCHMARK_ID,
        BenchmarkSourceKind.GIT,
        voyager_minecraft_revision(),
        VOYAGER_MINECRAFT_SOURCE_REPOSITORY,
        VOYAGER_MINECRAFT_PROTOCOL_DIGEST,
        metadata={
            "paper_venue": "TMLR 2024",
            "source_commit": VOYAGER_MINECRAFT_PAPER_COMMIT,
            "trial_count": str(VOYAGER_MINECRAFT_TRIAL_COUNT),
            "max_prompting_iterations": str(VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS),
            "world_seed_status": "not-published-by-paper",
            "default_task_reset": "reset-rejoin",
        },
    )


@lru_cache(maxsize=1)
def build_voyager_minecraft_lifelong_cut() -> NoetriumUnit:
    revision = voyager_minecraft_revision()
    objective = (
        "autonomously explore Minecraft, discover diverse items, "
        "and advance the technology tree"
    )
    tasks = tuple(
        task_unit(
            f"voyager-minecraft:lifelong:trial-{index:02d}",
            revision_id=revision,
            family="voyager_open_world_lifelong_learning",
            schema_id=VOYAGER_MINECRAFT_TASK_SCHEMA_ID,
            content_digest=None,
            content={
                "objective": objective,
                "trial_index": index,
                "protocol_digest": VOYAGER_MINECRAFT_PROTOCOL_DIGEST,
                "fresh_world": True,
                "initial_inventory": "paper-default",
                "max_prompting_iterations": VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
                "task_reset_semantics": "reset-rejoin-after-each-task",
            },
            lineage_refs=(
                f"paper-trial:{index}",
                "fresh-world:true",
                "world-seed:paper-unpublished",
                "max-prompting-iterations:160",
                "task-reset:reset-rejoin",
            ),
            package=task_package(
                "voyager.minecraft.open-world-lifelong-package.v1",
                canonical_digest({
                    "objective": objective,
                    "trial_index": index,
                    "max_prompting_iterations": VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
                }),
                environment_requirement_id="environment.minecraft.voyager-paper-release",
                verifier_requirement_id="benchmark.voyager.open-world-metrics",
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for index in range(1, VOYAGER_MINECRAFT_TRIAL_COUNT + 1)
    )
    task_ids = tuple(task_id(row) for row in tasks)
    return benchmark_cut_unit(
        VOYAGER_MINECRAFT_BENCHMARK_ID,
        revision,
        VOYAGER_MINECRAFT_PROTOCOL_DIGEST,
        VOYAGER_MINECRAFT_TASK_SCHEMA_ID,
        tasks,
        splits=(
            split_unit("all", task_ids),
            split_unit(VOYAGER_MINECRAFT_LIFELONG_SPLIT, task_ids),
        ),
        selection_policy={
            "protocol_digest": VOYAGER_MINECRAFT_PROTOCOL_DIGEST,
            "trial_task_ids": task_ids,
            "trial_count": VOYAGER_MINECRAFT_TRIAL_COUNT,
        },
    )


def bind_voyager_minecraft_lifelong_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_voyager_minecraft_source(),
        task_set=build_voyager_minecraft_lifelong_cut(),
    )


__all__ = [
    "VOYAGER_MINECRAFT_BENCHMARK_ID",
    "VOYAGER_MINECRAFT_LIFELONG_SPLIT",
    "VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS",
    "VOYAGER_MINECRAFT_PAPER_COMMIT",
    "VOYAGER_MINECRAFT_PROTOCOL_DIGEST",
    "VOYAGER_MINECRAFT_SOURCE_REPOSITORY",
    "VOYAGER_MINECRAFT_TASK_SCHEMA_ID",
    "VOYAGER_MINECRAFT_TRIAL_COUNT",
    "bind_voyager_minecraft_lifelong_cut",
    "build_voyager_minecraft_lifelong_cut",
    "build_voyager_minecraft_source",
    "voyager_minecraft_revision",
]
