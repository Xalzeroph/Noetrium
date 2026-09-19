from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, distance, error, integer, item_count, number, position, text


def _collect_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "collect_block"
    value = allowed(action_type, payload, {"block", "query", "count", "max_distance"})
    name = value.get("block", value.get("query"))
    result = {
        "block": text(action_type, "block", name),
        "count": integer(action_type, "count", value.get("count", 1), minimum=1, maximum=64),
        "max_distance": number(action_type, "max_distance", value.get("max_distance", 48)),
    }
    if not 4 <= result["max_distance"] <= 128:
        raise error(action_type, "FIELD_RANGE", "max_distance must be in [4, 128]")
    return result


def _craft_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    return item_count("craft_item", allowed("craft_item", payload, {"item", "count"}))


def _discard_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    return item_count("discard_item", allowed("discard_item", payload, {"item", "count"}))


def _smelt_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "smelt_item"
    value = allowed(
        action_type,
        payload,
        {"item", "count", "fuel", "max_distance", "max_wait_s"},
    )
    result = item_count(action_type, value, maximum=8)
    if value.get("fuel") is not None:
        result["fuel"] = text(action_type, "fuel", value["fuel"])
    result["max_distance"] = distance(
        action_type,
        "max_distance",
        value.get("max_distance"),
        default=32,
    )
    result["max_wait_s"] = distance(
        action_type,
        "max_wait_s",
        value.get("max_wait_s"),
        default=90,
        minimum=10,
        maximum=180,
    )
    return result


def _max_distance_32(action_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    value = allowed(action_type, payload, {"max_distance"})
    return {
        "max_distance": distance(
            action_type,
            "max_distance",
            value.get("max_distance"),
            default=32,
        )
    }


def _clear_furnace(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _max_distance_32("clear_furnace", payload)


def _chest_inspect(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _max_distance_32("chest_inspect", payload)


def _place_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "place_block"
    value = allowed(action_type, payload, {"item", "position"})
    result = {"item": text(action_type, "item", value.get("item"))}
    if value.get("position") is not None:
        result["position"] = position(action_type, value["position"])
    return result


def _pickup_items(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "pickup_items"
    value = allowed(action_type, payload, {"max_distance", "max_items"})
    return {
        "max_distance": distance(
            action_type,
            "max_distance",
            value.get("max_distance"),
            default=16,
            maximum=64,
        ),
        "max_items": integer(
            action_type,
            "max_items",
            value.get("max_items", 8),
            minimum=1,
            maximum=32,
        ),
    }


def _auto_light(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "auto_light"
    value = allowed(action_type, payload, {"max_distance"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=16)
    }


def _equip_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "equip_item"
    value = allowed(action_type, payload, {"item", "destination"})
    destination = str(value.get("destination", "hand"))
    allowed_destinations = {"hand", "off-hand", "head", "torso", "legs", "feet"}
    if destination not in allowed_destinations:
        raise error(
            action_type,
            "FIELD_VALUE",
            f"destination must be one of {sorted(allowed_destinations)}",
        )
    return {
        "item": text(action_type, "item", value.get("item")),
        "destination": destination,
    }


def _consume_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "consume_item"
    value = allowed(action_type, payload, {"item"})
    return {"item": text(action_type, "item", value.get("item"))}


def _give_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "give_item"
    value = allowed(action_type, payload, {"player", "item", "count"})
    return {
        "player": text(action_type, "player", value.get("player"), maximum=16),
        **item_count(action_type, value),
    }


def _chest_transfer(action_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    value = allowed(action_type, payload, {"item", "count", "max_distance"})
    result = item_count(action_type, value)
    result["max_distance"] = distance(
        action_type,
        "max_distance",
        value.get("max_distance"),
        default=32,
    )
    return result


def _chest_deposit(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _chest_transfer("chest_deposit", payload)


def _chest_withdraw(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _chest_transfer("chest_withdraw", payload)


def _till_and_sow(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "till_and_sow"
    value = allowed(action_type, payload, {"seed", "max_distance"})
    return {
        "seed": text(action_type, "seed", value.get("seed")),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32),
    }


CODECS = {
    "collect_block": _collect_block,
    "craft_item": _craft_item,
    "smelt_item": _smelt_item,
    "clear_furnace": _clear_furnace,
    "place_block": _place_block,
    "pickup_items": _pickup_items,
    "auto_light": _auto_light,
    "equip_item": _equip_item,
    "consume_item": _consume_item,
    "discard_item": _discard_item,
    "give_item": _give_item,
    "chest_deposit": _chest_deposit,
    "chest_withdraw": _chest_withdraw,
    "chest_inspect": _chest_inspect,
    "till_and_sow": _till_and_sow,
}

__all__ = ["CODECS"]
