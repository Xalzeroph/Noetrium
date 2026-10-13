from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, distance, error, integer, item_count, number, position, text


def _collect_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "collect_block"
    value = allowed(
        action_type,
        payload,
        {"block", "query", "count", "max_distance", "position", "effect", "tool"},
    )
    name = value.get("block", value.get("query"))
    result = {
        "block": text(action_type, "block", name),
        "count": integer(action_type, "count", value.get("count", 1), minimum=1, maximum=64),
        "max_distance": number(action_type, "max_distance", value.get("max_distance", 48)),
    }
    if value.get("tool") is not None:
        result["tool"] = text(action_type, "tool", value["tool"])
    if not 4 <= result["max_distance"] <= 128:
        raise error(action_type, "FIELD_RANGE", "max_distance must be in [4, 128]")
    effect = value.get("effect", "collect")
    if effect not in {"collect", "remove"} or not isinstance(effect, str):
        raise error(action_type, "FIELD_VALUE", "effect must be collect or remove")
    if effect == "remove" and value.get("position") is None:
        raise error(action_type, "EXACT_TARGET_REQUIRED", "block removal needs an observed exact position")
    if effect == "remove" and value.get("tool") is not None:
        raise error(action_type, "FIELD_VALUE", "tool constrains collection only, not exact removal")
    if effect == "remove":
        result["effect"] = "remove"
    if value.get("position") is not None:
        target = position(action_type, value["position"])
        if any(not coordinate.is_integer() for coordinate in target.values()):
            raise error(action_type, "POSITION_BLOCK_GRID", "exact block position must use integer coordinates")
        if result["count"] != 1:
            raise error(action_type, "EXACT_TARGET_COUNT", "exact block position requires count=1")
        result["position"] = {key: int(n) for key, n in target.items()}
    return result


def _excavate_region(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "excavate_region"
    value = allowed(
        action_type, payload,
        {"corner_a", "corner_b", "max_blocks", "max_distance"},
    )
    corners: dict[str, dict[str, int]] = {}
    for name in ("corner_a", "corner_b"):
        parsed = position(action_type, value.get(name))
        if any(not coordinate.is_integer() for coordinate in parsed.values()):
            raise error(
                action_type, "POSITION_BLOCK_GRID",
                f"{name} must use integer block coordinates",
            )
        corners[name] = {axis: int(number) for axis, number in parsed.items()}
    extents = [
        abs(corners["corner_a"][axis] - corners["corner_b"][axis]) + 1
        for axis in ("x", "y", "z")
    ]
    if any(extent > 16 for extent in extents):
        raise error(action_type, "REGION_EXTENT", "each excavation extent must be at most 16 blocks")
    volume = extents[0] * extents[1] * extents[2]
    if volume > 128:
        raise error(action_type, "REGION_VOLUME", "excavation region volume must be at most 128 blocks")
    return {
        **corners,
        "max_blocks": integer(
            action_type, "max_blocks", value.get("max_blocks", 16),
            minimum=1, maximum=32,
        ),
        "max_distance": distance(
            action_type, "max_distance", value.get("max_distance"),
            default=32, minimum=4, maximum=64,
        ),
    }


def _craft_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    return item_count("craft_item", allowed("craft_item", payload, {"item", "count"}))


def _craft_grid(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "craft_grid"
    value = allowed(action_type, payload, {"grid", "station", "max_distance"})
    station = text(action_type, "station", value.get("station"))
    if station not in {"inventory", "table"}:
        raise error(action_type, "FIELD_VALUE", "station must be inventory or table")
    grid = text(action_type, "grid", value.get("grid"))
    cells = tuple(name.strip() for name in grid.split(","))
    if len(cells) != (4 if station == "inventory" else 9):
        raise error(action_type, "FIELD_VALUE", "craft grid must have exactly 4 or 9 cells")
    if any(
        not name or (
            name != "_" and (
                not name.replace("_", "").isalnum()
                or not name.islower()
            )
        )
        for name in cells
    ):
        raise error(action_type, "FIELD_VALUE", "grid items must be canonical lowercase names or _")
    if not any(name != "_" for name in cells):
        raise error(action_type, "FIELD_VALUE", "craft grid cannot be empty")
    return {
        "grid": ",".join(cells),
        "station": station,
        "max_distance": distance(
            action_type, "max_distance", value.get("max_distance"), default=32
        ),
    }


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


def _enchant_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "enchant_item"
    value = allowed(action_type, payload, {"item", "choice", "max_distance"})
    return {
        "item": text(action_type, "item", value.get("item")),
        "choice": integer(action_type, "choice", value.get("choice", 0), minimum=0, maximum=2),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32),
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
    value = allowed(action_type, payload, {"max_distance", "max_items", "item"})
    result = {
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
    if value.get("item") is not None:
        result["item"] = text(action_type, "item", value["item"])
    return result


def _auto_light(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "auto_light"
    value = allowed(action_type, payload, {"max_distance"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=16)
    }


def _equip_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "equip_item"
    value = allowed(action_type, payload, {"item", "destination"})
    raw_destination = str(value.get("destination", "hand")).strip().lower()
    destination_aliases = {
        "hand": "hand",
        "main_hand": "hand",
        "main-hand": "hand",
        "mainhand": "hand",
        "off-hand": "off-hand",
        "off_hand": "off-hand",
        "offhand": "off-hand",
        "head": "head",
        "helmet": "head",
        "torso": "torso",
        "chest": "torso",
        "chestplate": "torso",
        "body": "torso",
        "legs": "legs",
        "leggings": "legs",
        "feet": "feet",
        "boots": "feet",
    }
    destination = destination_aliases.get(raw_destination, raw_destination)
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
    "excavate_region": _excavate_region,
    "craft_item": _craft_item,
    "craft_grid": _craft_grid,
    "smelt_item": _smelt_item,
    "enchant_item": _enchant_item,
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
