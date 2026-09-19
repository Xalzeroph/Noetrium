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
    "defend_self": {},
    "discard_item": {"item": "dirt"},
    "dismount": {},
    "equip_item": {"item": "iron_sword"},
    "fish": {},
    "follow_player": {"player": "ResearchBot"},
    "give_item": {"player": "ResearchBot", "item": "bread"},
    "go_to_bed": {},
    "goto": {"position": {"x": 1, "y": 2, "z": 3}},
    "goto_entity": {"entity": "cow"},
    "mount": {},
    "move_away": {},
    "observe_entities": {},
    "pickup_items": {},
    "place_block": {"item": "cobblestone"},
    "ranged_attack": {"entity": "skeleton"},
    "registry_search": {"query": "oak_log"},
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
    assert len(ACTION_CODECS) == len(MINECRAFT_ACTION_TYPES) == 38


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


def test_action_codec_registry_is_runtime_immutable() -> None:
    with pytest.raises(TypeError):
        ACTION_CODECS["wait"] = ACTION_CODECS["chat"]  # type: ignore[index]
