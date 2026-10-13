from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, error, integer, number, position, text


def _wait(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "wait"
    value = allowed(action_type, payload, {"ms"})
    return {
        "ms": integer(action_type, "ms", value.get("ms", 500), minimum=0, maximum=10000)
    }


def _chat(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "chat"
    value = allowed(action_type, payload, {"message"})
    return {"message": text(action_type, "message", value.get("message"))}


def _observe_blocks(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "observe_blocks"
    value = allowed(
        action_type,
        payload,
        {"query", "position", "max_distance", "limit"},
    )
    result: dict[str, Any] = {
        "max_distance": number(
            action_type,
            "max_distance",
            value.get("max_distance", 16),
        )
    }
    if not 1 <= result["max_distance"] <= 128:
        raise error(
            action_type,
            "FIELD_RANGE",
            "max_distance must be in [1, 128]",
        )
    result["limit"] = integer(
        action_type,
        "limit",
        value.get("limit", 32),
        minimum=1,
        maximum=100,
    )
    if value.get("position") is not None:
        if value.get("query") is not None or "limit" in value:
            raise error(
                action_type, "EXACT_OBSERVATION_MODE",
                "position is exclusive with query and limit",
            )
        target = position(action_type, value["position"])
        if any(not coordinate.is_integer() for coordinate in target.values()):
            raise error(
                action_type, "POSITION_BLOCK_GRID",
                "exact observation position must use integer block coordinates",
            )
        result.pop("limit", None)
        result["position"] = {axis: int(number) for axis, number in target.items()}
    elif value.get("query") is not None:
        result["query"] = text(
            action_type,
            "query",
            value.get("query"),
        )
    return result


def _observe_entities(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "observe_entities"
    value = allowed(action_type, payload, {"max_distance", "limit"})
    result = {
        "max_distance": number(action_type, "max_distance", value.get("max_distance", 16))
    }
    if not 1 <= result["max_distance"] <= 128:
        raise error(action_type, "FIELD_RANGE", "max_distance must be in [1, 128]")
    result["limit"] = integer(
        action_type,
        "limit",
        value.get("limit", 32),
        minimum=1,
        maximum=100,
    )
    return result


def _registry_search(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "registry_search"
    value = allowed(action_type, payload, {"query", "limit"})
    return {
        "query": text(action_type, "query", value.get("query")),
        "limit": integer(
            action_type,
            "limit",
            value.get("limit", 20),
            minimum=1,
            maximum=100,
        ),
    }


def _recipe_lookup(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "recipe_lookup"
    value = allowed(action_type, payload, {"item", "limit"})
    return {
        "item": text(action_type, "item", value.get("item")),
        "limit": integer(
            action_type, "limit", value.get("limit", 20),
            minimum=1, maximum=100,
        ),
    }


def _recipe_dependencies(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "recipe_dependencies"
    value = allowed(action_type, payload, {"item", "count"})
    return {
        "item": text(action_type, "item", value.get("item")),
        "count": integer(
            action_type, "count", value.get("count", 1),
            minimum=1, maximum=64,
        ),
    }


def _describe_action(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "describe_action"
    value = allowed(action_type, payload, {"action_type"})
    return {"action_type": text(action_type, "action_type", value.get("action_type"))}


CODECS = {
    "describe_action": _describe_action,
    "wait": _wait,
    "chat": _chat,
    "observe_blocks": _observe_blocks,
    "observe_entities": _observe_entities,
    "registry_search": _registry_search,
    "recipe_lookup": _recipe_lookup,
    "recipe_dependencies": _recipe_dependencies,
}

__all__ = ["CODECS"]
