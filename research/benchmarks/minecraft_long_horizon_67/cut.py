from __future__ import annotations

from dataclasses import dataclass, field

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


MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID = "minecraft-long-horizon-67"
MINECRAFT_LONG_HORIZON_67_TASK_SCHEMA_ID = (
    "minecraft-long-horizon-67.goal.v1"
)
MINECRAFT_LONG_HORIZON_67_REPOSITORY = (
    "https://github.com/iLearn-Lab/NeurIPS24-Optimus-1"
)
MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT = (
    "e789c58f53a4f831d67c4d6aaa008dbfd198a229"
)
MINECRAFT_LONG_HORIZON_67_PAPER_URI = (
    "https://proceedings.neurips.cc/paper_files/paper/2024/hash/"
    "5949a8750a110ce1f0631b1776c500a2-Abstract-Conference.html"
)
MINECRAFT_LONG_HORIZON_67_ALL_SPLIT = "all"
MINECRAFT_LONG_HORIZON_67_TASK_COUNT = 67
MINECRAFT_LONG_HORIZON_RELEASE_CONFIG_COUNT = 73

_CONFIG_BLOBS = (
    ("wooden", "2c4ca1871240ddf6efaad820ba617c1f61dcb3fb"),
    ("stone", "7040d041c51b6e04cfd92d0b0e3e2b1627d95dba"),
    ("iron", "ecf666f0eed8831913ab5f3b047af449e2e5e187"),
    ("golden", "93b9040f3a1a93c0637d93afcb49e8b7f2cd80ca"),
    ("redstone", "8ec0cfad10247372814eb7cbb9961a73c8a11a14"),
    ("diamond", "3ed65fa3e33ae5025c43fd2ab829c1168e5f2f62"),
    ("armor", "9ff839e08d00a1d2a59eac35698b1077113beee4"),
)

MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS = (
    ("wooden", 10),
    ("stone", 9),
    ("iron", 16),
    ("golden", 6),
    ("redstone", 6),
    ("diamond", 7),
    ("armor", 13),
)

MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS = (
    ("wooden", 3600),
    ("stone", 7200),
    ("iron", 12000),
    ("golden", 36000),
    ("redstone", 36000),
    ("diamond", 36000),
    ("armor", 36000),
)

MINECRAFT_LONG_HORIZON_67_GROUP_AVG_SUBGOALS = (
    ("wooden", 5),
    ("stone", 9),
    ("iron", 13),
    ("golden", 16),
    ("redstone", 17),
    ("diamond", 15),
    ("armor", 16),
)

# Exact paper cut recovered by intersecting the paper group cardinalities
# with the paper-era official 73-row release configuration. These six
# release-only auxiliary acquisition rows are excluded by the 67-task paper
# protocol; the Diamond acquisition goal remains because the paper explicitly
# counts all seven Diamond rows and names mining a diamond as its example task.
MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS = (
    ("wooden", 10, "chop a tree"),
    ("wooden", 11, "dig down to mine dirt"),
    ("stone", 9, "dig down to mine cobblestone"),
    ("iron", 16, "dig down to mine iron ore"),
    ("golden", 6, "dig down to mine gold ore"),
    ("redstone", 6, "dig down to mine redstone"),
)

_GROUP_TASKS = (
    (
        "wooden",
        (
            "Craft a wooden shovel",
            "Craft a wooden pickaxe",
            "Craft a wooden axe",
            "Craft a wooden hoe",
            "Craft a stick",
            "Craft a crafting table",
            "Craft a wooden sword",
            "Craft a chest",
            "Craft a bowl",
            "Craft a ladder",
        ),
    ),
    (
        "stone",
        (
            "Craft a stone shovel",
            "Craft a stone pickaxe",
            "Craft a stone axe",
            "Craft a stone hoe",
            "Smelt a charcoal",
            "Craft a smoker",
            "Craft a stone sword",
            "Craft a furnace",
            "Craft a torch",
        ),
    ),
    (
        "iron",
        (
            "Craft a iron shovel",
            "Craft a iron pickaxe",
            "Craft a iron axe",
            "Craft a iron hoe",
            "Craft a bucket",
            "Craft a hopper",
            "Craft a rail",
            "Craft a iron sword",
            "Craft a shears",
            "Craft a smithing table",
            "Craft a tripwire hook",
            "Craft a chain",
            "Craft an iron bars",
            "Craft an iron nugget",
            "Craft a blast furnace",
            "Craft a stonecutter",
        ),
    ),
    (
        "golden",
        (
            "Craft a golden shovel",
            "Craft a golden pickaxe",
            "Craft a golden axe",
            "Craft a golden hoe",
            "Craft a golden sword",
            "Smelt and craft a gold ingot",
        ),
    ),
    (
        "redstone",
        (
            "Craft a piston",
            "Craft a redstone torch",
            "Craft an activator rail",
            "Craft a compass",
            "Craft a dropper",
            "Craft a note block",
        ),
    ),
    (
        "diamond",
        (
            "Craft a diamond shovel",
            "Craft a diamond pickaxe",
            "Craft a diamond axe",
            "Craft a diamond hoe",
            "Craft a diamond sword",
            "Dig down and mine a diamond",
            "Craft a jukebox",
        ),
    ),
    (
        "armor",
        (
            "Craft shield",
            "Craft iron chestplate",
            "Craft iron boots",
            "Craft iron leggings",
            "Craft iron helmet",
            "Craft diamond helmet",
            "Craft diamond chestplate",
            "Craft diamond leggings",
            "Craft diamond boots",
            "Craft golden helmet",
            "Craft golden leggings",
            "Craft golden boots",
            "Craft golden chestplate",
        ),
    ),
)


@dataclass(frozen=True, slots=True, order=True)
class MinecraftLongHorizon67Task:
    group: str
    config_id: int
    instruction: str
    max_steps: int
    config_blob_sha: str
    content_digest: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        counts = dict(MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS)
        if self.group not in counts:
            raise ValueError("unknown Minecraft long-horizon task group")
        if type(self.config_id) is not int or not 0 <= self.config_id < counts[self.group]:
            raise ValueError("Minecraft long-horizon config id is outside paper cut")
        if type(self.instruction) is not str or not self.instruction.strip():
            raise ValueError("Minecraft long-horizon instruction must be text")
        if self.max_steps != dict(
            MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS
        )[self.group]:
            raise ValueError("Minecraft long-horizon step budget drifted")
        if len(self.config_blob_sha) != 40:
            raise ValueError("Minecraft config blob must be git SHA-1")
        object.__setattr__(
            self,
            "content_digest",
            canonical_digest(
                {
                    "source_commit": MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT,
                    "config_blob_sha": self.config_blob_sha,
                    "group": self.group,
                    "config_id": self.config_id,
                    "instruction": self.instruction,
                    "max_steps": self.max_steps,
                    "initial_inventory": (),
                    "minecraft_version": "1.16.5",
                    "environment_fps": 20,
                }
            ),
        )

    @property
    def task_id(self) -> str:
        return (
            f"{MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID}:"
            f"{self.group}:{self.config_id:02d}"
        )


def _records() -> tuple[MinecraftLongHorizon67Task, ...]:
    blobs = dict(_CONFIG_BLOBS)
    budgets = dict(MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS)
    rows = tuple(
        MinecraftLongHorizon67Task(
            group=group,
            config_id=index,
            instruction=instruction,
            max_steps=budgets[group],
            config_blob_sha=blobs[group],
        )
        for group, instructions in _GROUP_TASKS
        for index, instruction in enumerate(instructions)
    )
    if len(rows) != MINECRAFT_LONG_HORIZON_67_TASK_COUNT:
        raise RuntimeError("Minecraft long-horizon paper task count drifted")
    if tuple(
        (group, len(instructions))
        for group, instructions in _GROUP_TASKS
    ) != MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS:
        raise RuntimeError("Minecraft long-horizon group cardinality drifted")
    return rows


MINECRAFT_LONG_HORIZON_67_TASKS = _records()

MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST = canonical_digest(
    {
        "benchmark_id": MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
        "paper_uri": MINECRAFT_LONG_HORIZON_67_PAPER_URI,
        "source_commit": MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT,
        "config_blobs": _CONFIG_BLOBS,
        "release_config_count": MINECRAFT_LONG_HORIZON_RELEASE_CONFIG_COUNT,
        "paper_task_count": MINECRAFT_LONG_HORIZON_67_TASK_COUNT,
        "paper_group_counts": MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS,
        "paper_group_max_steps": MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS,
        "paper_group_average_subgoals": (
            MINECRAFT_LONG_HORIZON_67_GROUP_AVG_SUBGOALS
        ),
        "excluded_release_rows": (
            MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS
        ),
        "selected_task_digests": tuple(
            row.content_digest for row in MINECRAFT_LONG_HORIZON_67_TASKS
        ),
        "initial_inventory": (),
        "minecraft_version": "1.16.5",
        "environment_fps": 20,
    }
)


def minecraft_long_horizon_67_revision() -> str:
    return (
        "neurips2024@"
        f"{MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT}:"
        f"protocol:{MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST}"
    )


def build_minecraft_long_horizon_67_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=minecraft_long_horizon_67_revision(),
        locator=MINECRAFT_LONG_HORIZON_67_REPOSITORY,
        content_digest=MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
        metadata={
            "paper_uri": MINECRAFT_LONG_HORIZON_67_PAPER_URI,
            "paper_venue": "NeurIPS 2024",
            "source_commit": MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT,
            "release_config_count": "73",
            "paper_task_count": "67",
            "paper_group_count": "7",
            "minecraft_version": "1.16.5",
            "environment_fps": "20",
            "initial_inventory": "empty",
            "selection": "paper-cardinality-over-paper-era-release-configs",
        },
    )


def build_minecraft_long_horizon_67_cut() -> BenchmarkTaskSet:
    revision = minecraft_long_horizon_67_revision()
    tasks = tuple(
        TaskDefinition(
            task_id=row.task_id,
            revision_id=revision,
            family=f"minecraft_long_horizon_{row.group}",
            schema_id=MINECRAFT_LONG_HORIZON_67_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"group:{row.group}",
                f"release-config-id:{row.config_id}",
                f"release-config-blob:{row.config_blob_sha}",
                f"max-environment-steps:{row.max_steps}",
                "initial-inventory:empty",
                "minecraft-version:1.16.5",
                "environment-fps:20",
            ),
            package=TaskPackageSpec(
                package_schema_id=(
                    "minecraft-long-horizon-67.task-package.v1"
                ),
                instruction_digest=row.content_digest,
                environment_requirement_id=(
                    "benchmark.minecraft-1.16.5-low-level-20fps"
                ),
                verifier_requirement_id=(
                    "benchmark.minecraft-long-horizon-goal-state.verifier"
                ),
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            ),
        )
        for row in MINECRAFT_LONG_HORIZON_67_TASKS
    )
    tasks = tuple(sorted(tasks, key=lambda row: row.task_id))
    task_ids = tuple(row.task_id for row in tasks)
    splits = [TaskSetSplit(MINECRAFT_LONG_HORIZON_67_ALL_SPLIT, task_ids)]
    for group, _ in MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS:
        splits.append(
            TaskSetSplit(
                f"group:{group}",
                tuple(
                    row.task_id
                    for row in tasks
                    if row.family == f"minecraft_long_horizon_{group}"
                ),
            )
        )
    return BenchmarkTaskSet(
        benchmark_id=MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID,
        revision_id=revision,
        source_digest=MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
        task_schema_id=MINECRAFT_LONG_HORIZON_67_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=tuple(splits),
        selection_policy_digest=canonical_digest(
            {
                "protocol_digest": MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST,
                "task_ids": task_ids,
                "excluded_release_rows": (
                    MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS
                ),
            }
        ),
    )


def bind_minecraft_long_horizon_67_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_minecraft_long_horizon_67_source(),
        task_set=build_minecraft_long_horizon_67_cut(),
    )


__all__ = [
    "MINECRAFT_LONG_HORIZON_67_ALL_SPLIT",
    "MINECRAFT_LONG_HORIZON_67_BENCHMARK_ID",
    "MINECRAFT_LONG_HORIZON_67_EXCLUDED_RELEASE_ROWS",
    "MINECRAFT_LONG_HORIZON_67_GROUP_AVG_SUBGOALS",
    "MINECRAFT_LONG_HORIZON_67_GROUP_COUNTS",
    "MINECRAFT_LONG_HORIZON_67_GROUP_MAX_STEPS",
    "MINECRAFT_LONG_HORIZON_67_PAPER_URI",
    "MINECRAFT_LONG_HORIZON_67_PROTOCOL_DIGEST",
    "MINECRAFT_LONG_HORIZON_67_REPOSITORY",
    "MINECRAFT_LONG_HORIZON_67_SOURCE_COMMIT",
    "MINECRAFT_LONG_HORIZON_67_TASK_COUNT",
    "MINECRAFT_LONG_HORIZON_67_TASKS",
    "MINECRAFT_LONG_HORIZON_67_TASK_SCHEMA_ID",
    "MINECRAFT_LONG_HORIZON_RELEASE_CONFIG_COUNT",
    "MinecraftLongHorizon67Task",
    "bind_minecraft_long_horizon_67_cut",
    "build_minecraft_long_horizon_67_cut",
    "build_minecraft_long_horizon_67_source",
    "minecraft_long_horizon_67_revision",
]
