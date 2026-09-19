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

JARVIS1_OFFLINE_BENCHMARK_ID = "jarvis1-offline-185"
JARVIS1_OFFLINE_REPOSITORY = "https://github.com/CraftJarvis/JARVIS-1"
JARVIS1_OFFLINE_COMMIT = "aa9bd97debee045cb35b37564c71dee4c465b9ad"
JARVIS1_TASKS_PATH = "jarvis/assets/tasks.json"
JARVIS1_TASKS_BLOB_SHA = "8cc441f240cf080a957c9d2987fc4f0d062d3309"
JARVIS1_TASK_COUNT = 185
JARVIS1_ALL_SPLIT = "all-185"
JARVIS1_TASK_SCHEMA_ID = "jarvis1.offline-task-row.v1"

JARVIS1_GROUP_COUNTS = (
    ("hand", 2),
    ("building", 18),
    ("tool", 25),
    ("foodstuffs", 7),
    ("redstone", 27),
    ("brewing", 2),
    ("miscellaneous", 9),
    ("decoration", 11),
    ("transportation", 6),
    ("animals", 3),
    ("occupation_block", 5),
    ("equipment", 11),
    ("decorations", 1),
    ("combat", 5),
    ("iron", 6),
    ("colorful", 47),
)

JARVIS1_TASK_IDENTITIES = (
    (1, "hand", "painting"),
    (2, "hand", "white_banner"),
    (3, "building", "oak_wood"),
    (4, "building", "birch_wood"),
    (5, "building", "oak_slab"),
    (6, "building", "birch_slab"),
    (7, "building", "oak_planks"),
    (8, "building", "birch_planks"),
    (9, "building", "oak_log"),
    (10, "building", "birch_log"),
    (11, "building", "glass"),
    (12, "building", "stone"),
    (13, "tool", "wooden_shovel"),
    (14, "tool", "wooden_hoe"),
    (15, "foodstuffs", "bowl"),
    (16, "tool", "wooden_axe"),
    (17, "tool", "stone_shovel"),
    (18, "tool", "wooden_pickaxe"),
    (19, "foodstuffs", "golden_apple"),
    (20, "foodstuffs", "gold_nugget"),
    (21, "tool", "clock"),
    (22, "tool", "golden_pickaxe"),
    (23, "tool", "golden_chestplate"),
    (24, "tool", "golden_leggings"),
    (25, "tool", "golden_boots"),
    (26, "tool", "golden_helmet"),
    (27, "tool", "golden_axe"),
    (28, "tool", "golden_hoe"),
    (29, "tool", "stone_pickaxe"),
    (30, "tool", "stone_axe"),
    (31, "tool", "stone_hoe"),
    (32, "tool", "iron_pickaxe"),
    (33, "tool", "diamond_shovel"),
    (34, "tool", "iron_shovel"),
    (35, "tool", "diamond_pickaxe"),
    (36, "tool", "golden_shovel"),
    (37, "redstone", "oak_button"),
    (38, "redstone", "birch_button"),
    (39, "redstone", "redstone_torch"),
    (40, "redstone", "tripwire_hook"),
    (41, "redstone", "iron_trapdoor"),
    (42, "redstone", "iron_door"),
    (43, "redstone", "redstone_block"),
    (44, "redstone", "oak_door"),
    (45, "redstone", "birch_door"),
    (46, "redstone", "oak_fence_gate"),
    (47, "redstone", "birch_fence_gate"),
    (48, "redstone", "oak_trapdoor"),
    (49, "redstone", "birch_trapdoor"),
    (50, "brewing", "cauldron"),
    (51, "brewing", "glass_bottle"),
    (52, "miscellaneous", "diamond"),
    (53, "decoration", "jukebox"),
    (54, "miscellaneous", "stick"),
    (55, "miscellaneous", "gold_ingot"),
    (56, "miscellaneous", "paper"),
    (57, "miscellaneous", "iron_ore"),
    (58, "miscellaneous", "iron_ingot"),
    (59, "miscellaneous", "charcoal"),
    (60, "miscellaneous", "book"),
    (61, "miscellaneous", "bucket"),
    (62, "transportation", "rail"),
    (63, "transportation", "oak_boat"),
    (64, "transportation", "birch_boat"),
    (65, "transportation", "minecart"),
    (66, "foodstuffs", "cooked_chicken"),
    (67, "foodstuffs", "cooked_mutton"),
    (68, "animals", "white_wool"),
    (69, "animals", "white_bed"),
    (70, "foodstuffs", "cooked_porkchop"),
    (71, "foodstuffs", "cooked_beef"),
    (72, "occupation_block", "loom"),
    (73, "occupation_block", "smithing_table"),
    (74, "occupation_block", "barrel"),
    (75, "occupation_block", "composter"),
    (76, "occupation_block", "smoker"),
    (77, "equipment", "shield"),
    (78, "decorations", "item_frame"),
    (79, "equipment", "leather_helmet"),
    (80, "equipment", "leather_chestplate"),
    (81, "equipment", "leather_leggings"),
    (82, "equipment", "leather_boots"),
    (83, "equipment", "iron_helmet"),
    (84, "combat", "wooden_sword"),
    (85, "combat", "stone_sword"),
    (86, "combat", "golden_sword"),
    (87, "combat", "iron_sword"),
    (88, "combat", "diamond_sword"),
    (89, "decoration", "chain"),
    (90, "decoration", "crafting_table"),
    (91, "decoration", "chest"),
    (92, "decoration", "furnace"),
    (93, "decoration", "iron_bars"),
    (94, "decoration", "ladder"),
    (95, "decoration", "oak_fence"),
    (96, "decoration", "birch_fence"),
    (97, "equipment", "diamond_helmet"),
    (98, "equipment", "diamond_leggings"),
    (99, "equipment", "diamond_chestplate"),
    (100, "equipment", "diamond_boots"),
    (101, "tool", "diamond_hoe"),
    (102, "tool", "diamond_axe"),
    (103, "iron", "hopper"),
    (104, "iron", "iron_nugget"),
    (105, "iron", "iron_leggings"),
    (106, "iron", "iron_chestplate"),
    (107, "redstone", "piston"),
    (108, "iron", "heavy_weighted_pressure_plate"),
    (109, "iron", "shears"),
    (110, "redstone", "activator_rail"),
    (111, "redstone", "compass"),
    (112, "tool", "iron_hoe"),
    (113, "tool", "crossbow"),
    (114, "equipment", "iron_boots"),
    (115, "building", "acacia_wood"),
    (116, "building", "acacia_slab"),
    (117, "building", "acacia_planks"),
    (118, "building", "acacia_log"),
    (119, "redstone", "acacia_button"),
    (120, "redstone", "acacia_door"),
    (121, "redstone", "acacia_fence_gate"),
    (122, "redstone", "acacia_trapdoor"),
    (123, "transportation", "acacia_boat"),
    (124, "decoration", "acacia_fence"),
    (125, "building", "jungle_wood"),
    (126, "building", "jungle_slab"),
    (127, "building", "jungle_planks"),
    (128, "building", "jungle_log"),
    (129, "redstone", "jungle_button"),
    (130, "redstone", "jungle_door"),
    (131, "redstone", "jungle_fence_gate"),
    (132, "redstone", "jungle_trapdoor"),
    (133, "transportation", "jungle_boat"),
    (134, "decoration", "jungle_fence"),
    (135, "redstone", "redstone"),
    (136, "redstone", "dropper"),
    (137, "redstone", "note_block"),
    (138, "colorful", "yellow_dye"),
    (139, "colorful", "red_dye"),
    (140, "colorful", "magenta_dye"),
    (141, "colorful", "light_gray_dye"),
    (142, "colorful", "pink_dye"),
    (143, "colorful", "orange_dye"),
    (144, "colorful", "blue_dye"),
    (145, "colorful", "white_dye"),
    (146, "colorful", "light_blue_dye"),
    (147, "colorful", "purple_dye"),
    (148, "colorful", "yellow_wool"),
    (149, "colorful", "red_wool"),
    (150, "colorful", "magenta_wool"),
    (151, "colorful", "light_gray_wool"),
    (152, "colorful", "pink_wool"),
    (153, "colorful", "orange_wool"),
    (154, "colorful", "blue_wool"),
    (155, "colorful", "light_blue_wool"),
    (156, "colorful", "purple_wool"),
    (157, "colorful", "yellow_bed"),
    (158, "colorful", "red_bed"),
    (159, "colorful", "magenta_bed"),
    (160, "colorful", "light_gray_bed"),
    (161, "colorful", "pink_bed"),
    (162, "colorful", "orange_bed"),
    (163, "colorful", "orange_bed"),
    (164, "colorful", "blue_bed"),
    (165, "colorful", "light_blue_bed"),
    (166, "colorful", "purple_bed"),
    (167, "animals", "white_carpet"),
    (168, "colorful", "yellow_carpet"),
    (169, "colorful", "red_carpet"),
    (170, "colorful", "magenta_carpet"),
    (171, "colorful", "light_gray_carpet"),
    (172, "colorful", "pink_carpet"),
    (173, "colorful", "orange_carpet"),
    (174, "colorful", "blue_carpet"),
    (175, "colorful", "light_blue_carpet"),
    (176, "colorful", "purple_carpet"),
    (177, "colorful", "yellow_banner"),
    (178, "colorful", "red_banner"),
    (179, "colorful", "magenta_banner"),
    (180, "colorful", "light_gray_banner"),
    (181, "colorful", "pink_banner"),
    (182, "colorful", "orange_banner"),
    (183, "colorful", "blue_banner"),
    (184, "colorful", "light_blue_banner"),
    (185, "colorful", "purple_banner"),
)


def jarvis1_offline_source_digest() -> str:
    return canonical_digest({
        "repository": JARVIS1_OFFLINE_REPOSITORY,
        "commit": JARVIS1_OFFLINE_COMMIT,
        "path": JARVIS1_TASKS_PATH,
        "git_blob_sha": JARVIS1_TASKS_BLOB_SHA,
        "task_count": JARVIS1_TASK_COUNT,
        "group_counts": JARVIS1_GROUP_COUNTS,
        "task_identities": JARVIS1_TASK_IDENTITIES,
        "duplicate_task_name_policy": "preserve-source-row-index",
        "offline_evaluator": "offline_evaluation.py",
        "completion_monitor": "jarvis.assembly.evaluate.monitor_function",
    })


def jarvis1_offline_revision() -> str:
    return (
        f"jarvis1-offline@{JARVIS1_OFFLINE_COMMIT}:"
        f"{jarvis1_offline_source_digest()}"
    )


def build_jarvis1_offline_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=JARVIS1_OFFLINE_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=jarvis1_offline_revision(),
        locator=JARVIS1_OFFLINE_REPOSITORY,
        content_digest=jarvis1_offline_source_digest(),
        metadata={
            "tasks_path": JARVIS1_TASKS_PATH,
            "tasks_git_blob_sha": JARVIS1_TASKS_BLOB_SHA,
            "task_count": str(JARVIS1_TASK_COUNT),
            "group_count": str(len(JARVIS1_GROUP_COUNTS)),
            "duplicate_task_name": "orange_bed",
            "duplicate_policy": "preserve-both-source-rows",
            "evaluation_mode": "official-public-offline-fixed-memory",
        },
    )


def build_jarvis1_offline_cut() -> BenchmarkTaskSet:
    if len(JARVIS1_TASK_IDENTITIES) != JARVIS1_TASK_COUNT:
        raise RuntimeError("JARVIS-1 task identity count drifted")
    indices = tuple(row[0] for row in JARVIS1_TASK_IDENTITIES)
    if indices != tuple(range(1, JARVIS1_TASK_COUNT + 1)):
        raise RuntimeError("JARVIS-1 source-row indices drifted")
    counts: dict[str, int] = {}
    for _, group, _ in JARVIS1_TASK_IDENTITIES:
        counts[group] = counts.get(group, 0) + 1
    if tuple(sorted(counts.items())) != tuple(sorted(JARVIS1_GROUP_COUNTS)):
        raise RuntimeError("JARVIS-1 source group counts drifted")

    source = build_jarvis1_offline_source()
    tasks=tuple(
        TaskDefinition(
            task_id=f"jarvis1:{index:03d}:{task}",
            revision_id=JARVIS1_OFFLINE_COMMIT,
            family=f"jarvis1_{group}",
            schema_id=JARVIS1_TASK_SCHEMA_ID,
            content_digest=canonical_digest({
                "source_digest": source.content_digest,
                "source_row_index": index,
                "group": group,
                "task": task,
            }),
            lineage_refs=(
                f"source-row:{index}",
                f"group:{group}",
                f"task:{task}",
                f"source-blob:{JARVIS1_TASKS_BLOB_SHA}",
                "evaluation-mode:offline-fixed-memory",
            ),
            package=TaskPackageSpec(
                package_schema_id="jarvis1.minecraft.offline-task.v1",
                instruction_digest=canonical_digest({
                    "source_row_index": index,
                    "task": task,
                    "objective": f"Obtain {task}",
                }),
                environment_requirement_id=(
                    "environment.minecraft.jarvis1-public-offline"
                ),
                verifier_requirement_id=(
                    "benchmark.jarvis1.task-object-monitor"
                ),
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for index, group, task in JARVIS1_TASK_IDENTITIES
    )
    all_ids=tuple(row.task_id for row in tasks)
    group_splits=tuple(
        TaskSetSplit(
            f"group-{group.replace('_', '-')}",
            tuple(
                task.task_id
                for task, identity in zip(tasks, JARVIS1_TASK_IDENTITIES)
                if identity[1] == group
            ),
        )
        for group, _ in JARVIS1_GROUP_COUNTS
    )
    return BenchmarkTaskSet(
        benchmark_id=JARVIS1_OFFLINE_BENCHMARK_ID,
        revision_id=source.revision_id,
        source_digest=source.content_digest,
        task_schema_id=JARVIS1_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=tuple(sorted(
            (
                TaskSetSplit(JARVIS1_ALL_SPLIT, all_ids),
                *group_splits,
            ),
            key=lambda split: split.split_id,
        )),
        selection_policy_digest=canonical_digest({
            "source_digest": source.content_digest,
            "source_rows": JARVIS1_TASK_IDENTITIES,
            "group_counts": JARVIS1_GROUP_COUNTS,
            "split": JARVIS1_ALL_SPLIT,
        }),
    )


def bind_jarvis1_offline_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_jarvis1_offline_source(),
        task_set=build_jarvis1_offline_cut(),
    )


__all__ = [
    "JARVIS1_ALL_SPLIT",
    "JARVIS1_GROUP_COUNTS",
    "JARVIS1_OFFLINE_BENCHMARK_ID",
    "JARVIS1_OFFLINE_COMMIT",
    "JARVIS1_OFFLINE_REPOSITORY",
    "JARVIS1_TASK_COUNT",
    "JARVIS1_TASK_IDENTITIES",
    "JARVIS1_TASK_SCHEMA_ID",
    "JARVIS1_TASKS_BLOB_SHA",
    "JARVIS1_TASKS_PATH",
    "bind_jarvis1_offline_cut",
    "build_jarvis1_offline_cut",
    "build_jarvis1_offline_source",
    "jarvis1_offline_revision",
    "jarvis1_offline_source_digest",
]
