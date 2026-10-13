from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.runtime.world import (
    MinecraftWorldQuery,
)


def test_nearest_entity_preserves_distance_and_filtering() -> None:
    state = {
        "position": {"x": 0, "y": 0, "z": 0},
        "nearby_entities": [
            {"name": "cow", "position": {"x": 3, "y": 4, "z": 0}},
            {"name": "zombie", "position": {"x": 1, "y": 2, "z": 2}},
        ],
    }
    result = MinecraftWorldQuery.nearest_entity(state, "zom")
    assert result is not None
    assert result.entity["name"] == "zombie"
    assert result.distance == 3.0


def test_blocks_matching_stops_at_limit_semantically() -> None:
    blocks = [{"name": "stone", "i": i} for i in range(100)]
    assert tuple(row["i"] for row in MinecraftWorldQuery.blocks_matching({"nearby_blocks": blocks}, "stone", limit=3)) == (0, 1, 2)


def test_resource_summary_matches_inventory_count_semantics() -> None:
    state = {"inventory": {"minecraft:oak_log": 3, "minecraft:birch_log": 2, "minecraft:stone": 8}}
    assert MinecraftWorldQuery.resource_summary(state, ("log", "stone", "diamond")) == {"log": 5, "stone": 8, "diamond": 0}


def test_resource_summary_preserves_case_distinct_queries_and_empty_substring() -> None:
    state = {"inventory": {"Minecraft:Oak_Log": 3, "minecraft:stone": 2}}
    assert MinecraftWorldQuery.resource_summary(state, ("LOG", "log", "")) == {"LOG": 3, "log": 3, "": 5}


def test_aho_corasick_output_links_preserve_exhaustive_substring_semantics() -> None:
    from random import Random

    from noetrium_platform.capabilities.environment.minecraft.runtime.multi_pattern import (
        SubstringAggregatePlan,
    )

    random = Random(709311)
    alphabet = "abC"
    for _ in range(80):
        patterns = tuple(
            "".join(random.choice(alphabet) for _ in range(random.randint(0, 9)))
            for _ in range(random.randint(1, 35))
        )
        inventory = {
            f"slot{i}:" + "".join(random.choice(alphabet) for _ in range(random.randint(0, 40))):
                random.randrange(1, 20)
            for i in range(40)
        }
        plan = SubstringAggregatePlan.compile(patterns)
        observed = plan.aggregate(inventory)
        expected = {
            pattern: sum(
                number for name, number in inventory.items()
                if pattern.lower() in name.lower()
            )
            for pattern in patterns
        }
        assert observed == expected


def test_aho_corasick_suffix_families_store_each_terminal_once() -> None:
    from noetrium_platform.capabilities.environment.minecraft.runtime.multi_pattern import (
        SubstringAggregatePlan,
    )

    patterns = tuple("a" * n for n in range(1, 150))
    plan = SubstringAggregatePlan.compile(patterns)
    assert sum(len(terminals) for terminals in plan.outputs) == len(patterns)
    assert len(plan.transitions) == len(patterns) + 1
    assert plan.aggregate({"a" * 300: 5}) == {pattern: 5 for pattern in patterns}
