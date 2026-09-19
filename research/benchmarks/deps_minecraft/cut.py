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


DEPS_MINECRAFT_BENCHMARK_ID = "deps-minecraft-70"
DEPS_MINECRAFT_REPOSITORY = "https://github.com/CraftJarvis/MC-Planner"
DEPS_MINECRAFT_COMMIT = "df7067614ed527a2b56262441472886f1eb628ca"
DEPS_TASK_INFO_PATH = "data/task_info.json"
DEPS_TASK_INFO_BLOB_SHA = "09a2f650bc5a401d28916445530905509d5ba606"
DEPS_TASK_COUNT = 70
DEPS_ALL_SPLIT = "all-70"
DEPS_TASK_SCHEMA_ID = "deps.minecraft.paper-task.v1"

# (task_id, question, group, alias, episode_step_ceiling, target_object)
DEPS_TASK_IDENTITIES = (
    ("obtain_planks", "How to obtain planks?", "MT1", "basic", 3000, "planks"),
    ("obtain_stick", "How to obtain stick?", "MT1", "basic", 3000, "stick"),
    ("obtain_wooden_slab", "How to obtain wooden_slab?", "MT1", "basic", 3000, "wooden_slab"),
    ("obtain_wooden_button", "How to obtain wooden_button?", "MT1", "basic", 3000, "wooden_button"),
    ("obtain_wooden_pressure_plate", "How to obtain wooden_pressure_plate?", "MT1", "basic", 3000, "wooden_pressure_plate"),
    ("obtain_chest", "How to obtain chest?", "MT1", "basic", 3000, "chest"),
    ("obtain_oak_stairs", "How to obtain oak_stairs?", "MT1", "basic", 3000, "oak_stairs"),
    ("obtain_sign", "How to obtain sign?", "MT1", "basic", 3000, "sign"),
    ("obtain_fence", "How to obtain fence?", "MT1", "basic", 3000, "fence"),
    ("obtain_fence_gate", "How to obtain fence_gate?", "MT1", "basic", 3000, "fence_gate"),
    ("obtain_boat", "How to obtain boat?", "MT1", "basic", 3000, "boat"),
    ("obtain_trapdoor", "How to obtain trapdoor?", "MT1", "basic", 3000, "trapdoor"),
    ("obtain_bowl", "How to obtain bowl?", "MT1", "basic", 3000, "bowl"),
    ("obtain_stone_stairs", "How to obtain stone_stairs?", "MT4", "dig_down", 3000, "stone_stairs"),
    ("obtain_stone_slab", "How to obtain stone_slab?", "MT4", "dig_down", 3000, "stone_slab"),
    ("obtain_cobblestone_wall", "How to obtain cobblestone_wall?", "MT4", "dig_down", 3000, "cobblestone_wall"),
    ("obtain_lever", "How to obtain lever?", "MT4", "dig_down", 3000, "lever"),
    ("obtain_stone", "How to obtain stone?", "MT4", "dig_down", 3000, "stone"),
    ("obtain_stone_pressure_plate", "How to obtain stone_pressure_plate?", "MT4", "dig_down", 3000, "stone_pressure_plate"),
    ("obtain_coal", "How to obtain coal?", "MT4", "dig_down", 3000, "coal"),
    ("obtain_torch", "How to obtain torch?", "MT4", "dig_down", 3000, "torch"),
    ("obtain_crafting_table", "How to obtain crafting_table?", "MT2", "simple_tool", 3000, "crafting_table"),
    ("obtain_wooden_pickaxe", "How to obtain wooden_pickaxe?", "MT2", "simple_tool", 3000, "wooden_pickaxe"),
    ("obtain_wooden_axe", "How to obtain wooden_axe?", "MT2", "simple_tool", 3000, "wooden_axe"),
    ("obtain_wooden_hoe", "How to obtain wooden_hoe?", "MT2", "simple_tool", 3000, "wooden_hoe"),
    ("obtain_wooden_sword", "How to obtain wooden_sword?", "MT2", "simple_tool", 3000, "wooden_sword"),
    ("obtain_wooden_shovel", "How to obtain wooden_shovel?", "MT2", "simple_tool", 3000, "wooden_shovel"),
    ("obtain_furnace", "How to obtain furnace?", "MT2", "simple_tool", 3000, "furnace"),
    ("obtain_stone_pickaxe", "How to obtain stone_pickaxe?", "MT2", "simple_tool", 3000, "stone_pickaxe"),
    ("obtain_stone_axe", "How to obtain stone_axe?", "MT2", "simple_tool", 3000, "stone_axe"),
    ("obtain_stone_hoe", "How to obtain stone_hoe?", "MT2", "simple_tool", 3000, "stone_hoe"),
    ("obtain_stone_shovel", "How to obtain stone_shovel?", "MT2", "simple_tool", 3000, "stone_shovel"),
    ("obtain_stone_sword", "How to obtain stone_sword?", "MT2", "simple_tool", 3000, "stone_sword"),
    ("obtain_bucket", "How to obtain bucket?", "MT6", "complex_tool", 6000, "bucket"),
    ("obtain_shears", "How to obtain shears?", "MT6", "complex_tool", 6000, "shears"),
    ("obtain_iron_pickaxe", "How to obtain iron_pickaxe?", "MT6", "complex_tool", 6000, "iron_pickaxe"),
    ("obtain_iron_axe", "How to obtain iron_axe?", "MT6", "complex_tool", 6000, "iron_axe"),
    ("obtain_iron_hoe", "How to obtain iron_hoe?", "MT6", "complex_tool", 6000, "iron_hoe"),
    ("obtain_iron_shovel", "How to obtain iron_shovel?", "MT6", "complex_tool", 6000, "iron_shovel"),
    ("obtain_iron_sword", "How to obtain iron_sword?", "MT6", "complex_tool", 6000, "iron_sword"),
    ("obtain_leather_boots", "How to obtain leather_boots?", "MT5", "equipment", 6000, "leather_boots"),
    ("obtain_leather_chestplate", "How to obtain leather_chestplate?", "MT5", "equipment", 6000, "leather_chestplate"),
    ("obtain_leather_helmet", "How to obtain leather_helmet?", "MT5", "equipment", 6000, "leather_helmet"),
    ("obtain_leather_leggings", "How to obtain leather_leggings?", "MT5", "equipment", 6000, "leather_leggings"),
    ("obtain_iron_chestplate", "How to obtain iron_chestplate?", "MT5", "equipment", 6000, "iron_chestplate"),
    ("obtain_iron_leggings", "How to obtain iron_leggings?", "MT5", "equipment", 6000, "iron_leggings"),
    ("obtain_iron_helmet", "How to obtain iron_helmet?", "MT5", "equipment", 6000, "iron_helmet"),
    ("obtain_iron_boots", "How to obtain iron_boots?", "MT5", "equipment", 6000, "iron_boots"),
    ("obtain_shield", "How to obtain shield?", "MT5", "equipment", 6000, "shield"),
    ("obtain_iron_bars", "How to obtain iron_bars?", "MT7", "iron_stage", 9000, "iron_bars"),
    ("obtain_iron_nugget", "How to obtain iron_nugget?", "MT7", "iron_stage", 9000, "iron_nugget"),
    ("obtain_minecart", "How to obtain minecart?", "MT7", "iron_stage", 9000, "minecart"),
    ("obtain_hopper", "How to obtain hopper?", "MT7", "iron_stage", 9000, "hopper"),
    ("obtain_hopper_minecart", "How to obtain hopper_minecart?", "MT7", "iron_stage", 9000, "hopper_minecart"),
    ("obtain_furnace_minecart", "How to obtain furnace_minecart?", "MT7", "iron_stage", 9000, "furnace_minecart"),
    ("obtain_chest_minecart", "How to obtain chest_minecart?", "MT7", "iron_stage", 9000, "chest_minecart"),
    ("obtain_iron_door", "How to obtain iron_door?", "MT7", "iron_stage", 9000, "iron_door"),
    ("obtain_iron_trapdoor", "How to obtain iron_trapdoor?", "MT7", "iron_stage", 9000, "iron_trapdoor"),
    ("obtain_tripwire_hook", "How to obtain tripwire_hook?", "MT7", "iron_stage", 9000, "tripwire_hook"),
    ("obtain_heavy_weighted_pressure_plate", "How to obtain heavy_weighted_pressure_plate?", "MT7", "iron_stage", 9000, "heavy_weighted_pressure_plate"),
    ("obtain_rail", "How to obtain rail?", "MT7", "iron_stage", 9000, "rail"),
    ("obtain_cauldron", "How to obtain cauldron?", "MT7", "iron_stage", 9000, "cauldron"),
    ("obtain_bed", "How to obtain bed?", "MT3", "hunt_and_food", 6000, "bed"),
    ("obtain_painting", "How to obtain painting?", "MT3", "hunt_and_food", 6000, "painting"),
    ("obtain_carpet", "How to obtain carpet?", "MT3", "hunt_and_food", 6000, "carpet"),
    ("obtain_item_frame", "How to obtain item_frame?", "MT3", "hunt_and_food", 6000, "item_frame"),
    ("obtain_cooked_porkchop", "How to obtain cooked_porkchop?", "MT3", "hunt_and_food", 6000, "cooked_porkchop"),
    ("obtain_cooked_beef", "How to obtain cooked_beef?", "MT3", "hunt_and_food", 6000, "cooked_beef"),
    ("obtain_cooked_mutton", "How to obtain cooked_mutton?", "MT3", "hunt_and_food", 6000, "cooked_mutton"),
    ("obtain_diamond", "How to obtain diamond?", "MT8", "challenge", 12000, "diamond"),
)


def deps_source_content_digest() -> str:
    return canonical_digest({
        "repository": DEPS_MINECRAFT_REPOSITORY,
        "commit": DEPS_MINECRAFT_COMMIT,
        "task_info_path": DEPS_TASK_INFO_PATH,
        "task_info_git_blob_sha": DEPS_TASK_INFO_BLOB_SHA,
        "task_rows": DEPS_TASK_IDENTITIES,
        "task_count": DEPS_TASK_COUNT,
    })


def deps_revision() -> str:
    return (
        f"deps-neurips2023@{DEPS_MINECRAFT_COMMIT}:"
        f"{deps_source_content_digest()}"
    )


def build_deps_minecraft_source() -> BenchmarkSourceSpec:
    group_counts: dict[str, int] = {}
    episode_counts: dict[int, int] = {}
    for _, _, group, _, episode, _ in DEPS_TASK_IDENTITIES:
        group_counts[group] = group_counts.get(group, 0) + 1
        episode_counts[episode] = episode_counts.get(episode, 0) + 1
    return BenchmarkSourceSpec(
        source_id=DEPS_MINECRAFT_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=deps_revision(),
        locator=DEPS_MINECRAFT_REPOSITORY,
        content_digest=deps_source_content_digest(),
        metadata={
            "paper_venue": "NeurIPS 2023",
            "source_commit": DEPS_MINECRAFT_COMMIT,
            "task_info_path": DEPS_TASK_INFO_PATH,
            "task_info_git_blob_sha": DEPS_TASK_INFO_BLOB_SHA,
            "task_count": str(DEPS_TASK_COUNT),
            "groups": ",".join(sorted(group_counts)),
            "episode_step_ceilings": ",".join(
                str(value) for value in sorted(episode_counts)
            ),
            "evaluation": "minecraft-goal-completion",
        },
    )


def build_deps_minecraft_70_cut() -> BenchmarkTaskSet:
    if len(DEPS_TASK_IDENTITIES) != DEPS_TASK_COUNT:
        raise RuntimeError("DEPS official task count drifted")
    task_ids = tuple(row[0] for row in DEPS_TASK_IDENTITIES)
    if len(set(task_ids)) != DEPS_TASK_COUNT:
        raise RuntimeError("DEPS official task ids must be unique")

    source = build_deps_minecraft_source()
    canonical_identities = tuple(
        sorted(DEPS_TASK_IDENTITIES, key=lambda row: row[0])
    )
    tasks = tuple(
        TaskDefinition(
            task_id=f"deps-minecraft:{task_id}",
            revision_id=source.revision_id,
            family=f"deps_{group.lower()}_{alias}",
            schema_id=DEPS_TASK_SCHEMA_ID,
            content_digest=canonical_digest({
                "benchmark_source_digest": source.content_digest,
                "task_id": task_id,
                "question": question,
                "group": group,
                "alias": alias,
                "episode_step_ceiling": episode,
                "target_object": target_object,
            }),
            lineage_refs=(
                f"source-task:{task_id}",
                f"group:{group}",
                f"alias:{alias}",
                f"episode-step-ceiling:{episode}",
                f"target-object:{target_object}",
                f"source-blob:{DEPS_TASK_INFO_BLOB_SHA}",
            ),
            package=TaskPackageSpec(
                package_schema_id="deps.minecraft.goal-task.v1",
                instruction_digest=canonical_digest({
                    "question": question,
                    "target_object": target_object,
                    "episode_step_ceiling": episode,
                }),
                environment_requirement_id=(
                    "environment.minecraft.deps-paper-release"
                ),
                verifier_requirement_id=(
                    "benchmark.deps.minecraft-goal-success"
                ),
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for (
            task_id,
            question,
            group,
            alias,
            episode,
            target_object,
        ) in canonical_identities
    )
    all_ids = tuple(row.task_id for row in tasks)
    groups = tuple(sorted({row[2] for row in DEPS_TASK_IDENTITIES}))
    group_splits = tuple(
        TaskSetSplit(
            f"group-{group.lower()}",
            tuple(
                task.task_id
                for task, identity in zip(tasks, canonical_identities)
                if identity[2] == group
            ),
        )
        for group in groups
    )
    return BenchmarkTaskSet(
        benchmark_id=DEPS_MINECRAFT_BENCHMARK_ID,
        revision_id=source.revision_id,
        source_digest=source.content_digest,
        task_schema_id=DEPS_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(DEPS_ALL_SPLIT, all_ids),
            *group_splits,
        ),
        selection_policy_digest=canonical_digest({
            "source_digest": source.content_digest,
            "task_ids": all_ids,
            "groups": groups,
            "split": DEPS_ALL_SPLIT,
        }),
    )


def bind_deps_minecraft_70_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_deps_minecraft_source(),
        task_set=build_deps_minecraft_70_cut(),
    )


__all__ = [
    "DEPS_ALL_SPLIT",
    "DEPS_MINECRAFT_BENCHMARK_ID",
    "DEPS_MINECRAFT_COMMIT",
    "DEPS_MINECRAFT_REPOSITORY",
    "DEPS_TASK_COUNT",
    "DEPS_TASK_IDENTITIES",
    "DEPS_TASK_INFO_BLOB_SHA",
    "DEPS_TASK_INFO_PATH",
    "DEPS_TASK_SCHEMA_ID",
    "bind_deps_minecraft_70_cut",
    "build_deps_minecraft_70_cut",
    "build_deps_minecraft_source",
    "deps_revision",
    "deps_source_content_digest",
]
