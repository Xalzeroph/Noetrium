from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, distance, error, integer, number, position, text


def _goto(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "goto"
    value = allowed(action_type, payload, {"position", "radius"})
    if "position" not in value:
        raise error(action_type, "MISSING_FIELD", "position is required")
    result = {"position": position(action_type, value["position"])}
    result["radius"] = number(action_type, "radius", value.get("radius", 1.5))
    if not 0.1 <= result["radius"] <= 64:
        raise error(action_type, "FIELD_RANGE", "radius must be in [0.1, 64]")
    return result


def _goto_entity(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "goto_entity"
    value = allowed(action_type, payload, {"entity", "max_distance", "radius"})
    return {
        "entity": text(action_type, "entity", value.get("entity")),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=64),
        "radius": distance(action_type, "radius", value.get("radius"), default=2.5, minimum=1, maximum=16),
    }


def _move_away(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "move_away"
    value = allowed(action_type, payload, {"distance"})
    return {
        "distance": distance(
            action_type,
            "distance",
            value.get("distance"),
            default=8,
            maximum=64,
        )
    }


def _follow_player(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "follow_player"
    value = allowed(
        action_type,
        payload,
        {"player", "duration_s", "distance", "max_distance"},
    )
    return {
        "player": text(action_type, "player", value.get("player"), maximum=16),
        "duration_s": integer(action_type, "duration_s", value.get("duration_s", 10), minimum=1, maximum=60),
        "distance": distance(action_type, "distance", value.get("distance"), default=4, maximum=16),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=64),
    }


def _stay(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "stay"
    value = allowed(action_type, payload, {"duration_s"})
    return {
        "duration_s": integer(
            action_type,
            "duration_s",
            value.get("duration_s", 10),
            minimum=1,
            maximum=60,
        )
    }


CODECS = {
    "goto": _goto,
    "goto_entity": _goto_entity,
    "move_away": _move_away,
    "follow_player": _follow_player,
    "stay": _stay,
}

__all__ = ["CODECS"]
