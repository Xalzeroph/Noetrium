from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.minecraft.api.action_codecs import ACTION_CODECS
from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftActionContractError,
    validate_minecraft_action,
)


_MINIMAL_PAYLOADS: dict[str, dict[str, object]] = {
    "activate_nearest_block": {"block": "lever"},
    "attack_entity": {"entity_id": 1},
    "attack_nearest": {"entity": "zombie"},
    "attack_player": {"player": "ResearchBot"},
    "auto_light": {},
    "chat": {"message": "hello"},
    "chest_deposit": {"item": "oak_log"},
    "chest_inspect": {},
    "chest_withdraw": {"item": "oak_log"},
    "clear_furnace": {},
    "collect_block": {"block": "oak_log"},
    "consume_item": {"item": "bread"},
    "craft_item": {"item": "stick"},
    "craft_grid": {"grid": "oak_log,_,_,_", "station": "inventory"},
    "defend_self": {},
    "discard_item": {"item": "dirt"},
    "dismount": {},
    "equip_item": {"item": "iron_sword"},
    "fish": {},
    "follow_player": {"player": "ResearchBot"},
    "give_item": {"player": "ResearchBot", "item": "bread"},
    "go_to_bed": {},
    "goto": {"position": {"x": 1, "y": 2, "z": 3}},
    "goto_block": {"block": "crafting_table"},
    "goto_entity": {"entity": "cow"},
    "mount": {"entity": "horse"},
    "move_away": {},
    "observe_blocks": {},
    "observe_entities": {},
    "pickup_items": {},
    "place_block": {"item": "cobblestone"},
    "ranged_attack": {"entity": "skeleton"},
    "registry_search": {"query": "oak_log"},
    "recipe_lookup": {"item": "wooden_pickaxe"},
    "show_villager_trades": {},
    "smelt_item": {"item": "raw_iron"},
    "stay": {},
    "till_and_sow": {"seed": "wheat_seeds"},
    "trade_villager": {"trade_index": 0},
    "use_door": {},
    "use_tool_on": {"target": "oak_log"},
    "wait": {},
}


def test_action_codec_registry_exactly_matches_catalog() -> None:
    assert set(ACTION_CODECS) == MINECRAFT_ACTION_TYPES
    assert len(ACTION_CODECS) == len(MINECRAFT_ACTION_TYPES)
    assert "crafting_plan" not in ACTION_CODECS


@pytest.mark.parametrize("action_type", sorted(_MINIMAL_PAYLOADS))
def test_every_registered_action_accepts_minimal_valid_payload(action_type: str) -> None:
    result = validate_minecraft_action(action_type, _MINIMAL_PAYLOADS[action_type])
    assert isinstance(result, dict)


@pytest.mark.parametrize("action_type", sorted(_MINIMAL_PAYLOADS))
def test_every_registered_action_rejects_unknown_fields(action_type: str) -> None:
    payload = dict(_MINIMAL_PAYLOADS[action_type])
    payload["__unexpected__"] = True
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action(action_type, payload)
    assert captured.value.code == "UNKNOWN_FIELD"


def test_action_codec_public_entry_rejects_unregistered_and_non_mapping_payloads() -> None:
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action("not_registered", {})
    assert captured.value.code == "UNSUPPORTED_ACTION"
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action("wait", None)  # type: ignore[arg-type]
    assert captured.value.code == "PAYLOAD_TYPE"


def test_collect_block_accepts_an_exact_optional_tool_constraint() -> None:
    decoded = validate_minecraft_action(
        "collect_block",
        {"block": "diamond", "count": 1, "tool": "iron_pickaxe"},
    )
    assert decoded["tool"] == "iron_pickaxe"
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action(
            "collect_block",
            {
                "block": "stone",
                "count": 1,
                "tool": "iron_pickaxe",
                "position": {"x": 1, "y": 64, "z": 1},
                "effect": "remove",
            },
        )
    assert captured.value.code == "FIELD_VALUE"


def test_equip_destination_aliases_are_canonicalized_at_platform_boundary() -> None:
    aliases = {
        "main_hand": "hand",
        "main-hand": "hand",
        "mainhand": "hand",
        "off_hand": "off-hand",
        "offhand": "off-hand",
        "helmet": "head",
        "chest": "torso",
        "chestplate": "torso",
        "leggings": "legs",
        "boots": "feet",
    }
    for raw, expected in aliases.items():
        decoded = validate_minecraft_action(
            "equip_item", {"item": "iron_pickaxe", "destination": raw}
        )
        assert decoded["destination"] == expected


def test_action_codec_registry_is_runtime_immutable() -> None:
    with pytest.raises(TypeError):
        ACTION_CODECS["wait"] = ACTION_CODECS["chat"]  # type: ignore[index]


def test_excavate_region_codec_is_exact_and_bounded():
    assert validate_minecraft_action(
        "excavate_region",
        {
            "corner_a": {"x": 1, "y": 64, "z": 2},
            "corner_b": {"x": 4, "y": 65, "z": 2},
            "max_blocks": 8,
            "max_distance": 24,
        },
    ) == {
        "corner_a": {"x": 1, "y": 64, "z": 2},
        "corner_b": {"x": 4, "y": 65, "z": 2},
        "max_blocks": 8,
        "max_distance": 24.0,
    }
    with pytest.raises(ValueError, match="REGION_EXTENT"):
        validate_minecraft_action(
            "excavate_region",
            {
                "corner_a": {"x": 0, "y": 64, "z": 0},
                "corner_b": {"x": 16, "y": 64, "z": 0},
            },
        )
    with pytest.raises(ValueError, match="POSITION_BLOCK_GRID"):
        validate_minecraft_action(
            "excavate_region",
            {
                "corner_a": {"x": 0.5, "y": 64, "z": 0},
                "corner_b": {"x": 1, "y": 64, "z": 0},
            },
        )


def test_observe_blocks_exact_position_mode_is_exclusive_and_block_aligned():
    assert validate_minecraft_action(
        "observe_blocks", {"position": {"x": 2, "y": 64, "z": -1}, "max_distance": 12}
    ) == {
        "max_distance": 12.0,
        "position": {"x": 2, "y": 64, "z": -1},
    }
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action(
            "observe_blocks", {
                "position": {"x": 2, "y": 64, "z": -1},
                "query": "stone",
            }
        )
    assert captured.value.code == "EXACT_OBSERVATION_MODE"
    with pytest.raises(MinecraftActionContractError) as captured:
        validate_minecraft_action(
            "observe_blocks", {"position": {"x": 2.5, "y": 64, "z": -1}}
        )
    assert captured.value.code == "POSITION_BLOCK_GRID"
