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
