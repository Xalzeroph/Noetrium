from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, distance, error, integer, text


def _fish(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "fish"
    value = allowed(action_type, payload, {"casts", "max_wait_s"})
    return {
        "casts": integer(action_type, "casts", value.get("casts", 1), minimum=1, maximum=8),
        "max_wait_s": integer(action_type, "max_wait_s", value.get("max_wait_s", 60), minimum=10, maximum=120),
    }


def _mount(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "mount"
    value = allowed(action_type, payload, {"entity", "max_distance"})
    result = {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32)
    }
    if value.get("entity") is not None:
        result["entity"] = text(action_type, "entity", value["entity"])
    return result


def _dismount(payload: Mapping[str, Any]) -> dict[str, Any]:
    return allowed("dismount", payload, set())


def _use_door(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "use_door"
    value = allowed(action_type, payload, {"max_distance"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32)
    }


def _go_to_bed(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "go_to_bed"
    value = allowed(action_type, payload, {"max_distance", "max_wait_s"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=64),
        "max_wait_s": integer(action_type, "max_wait_s", value.get("max_wait_s", 30), minimum=10, maximum=60),
    }


def _activate_nearest_block(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "activate_nearest_block"
    value = allowed(action_type, payload, {"max_distance", "block"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32),
        "block": text(action_type, "block", value.get("block")),
    }


def _show_villager_trades(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "show_villager_trades"
    value = allowed(action_type, payload, {"max_distance"})
    return {
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32)
    }


def _trade_villager(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "trade_villager"
    value = allowed(action_type, payload, {"trade_index", "max_trades", "max_distance"})
    return {
        "trade_index": integer(action_type, "trade_index", value.get("trade_index"), minimum=0, maximum=63),
        "max_trades": integer(action_type, "max_trades", value.get("max_trades", 1), minimum=1, maximum=16),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=16, maximum=32),
    }


def _use_tool_on(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "use_tool_on"
    value = allowed(action_type, payload, {"target", "target_type", "max_distance"})
    target_type = str(value.get("target_type", "block"))
    if target_type not in {"block", "entity"}:
        raise error(action_type, "FIELD_VALUE", "target_type must be block or entity")
    return {
        "target": text(action_type, "target", value.get("target")),
        "target_type": target_type,
        "max_distance": distance(
            action_type,
            "max_distance",
            value.get("max_distance"),
            default=16,
            maximum=32,
        ),
    }


CODECS = {
    "fish": _fish,
    "mount": _mount,
    "dismount": _dismount,
    "use_door": _use_door,
    "go_to_bed": _go_to_bed,
    "activate_nearest_block": _activate_nearest_block,
    "show_villager_trades": _show_villager_trades,
    "trade_villager": _trade_villager,
    "use_tool_on": _use_tool_on,
}

__all__ = ["CODECS"]
