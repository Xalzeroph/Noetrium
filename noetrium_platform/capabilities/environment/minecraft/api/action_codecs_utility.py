from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, error, integer, number, text


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


CODECS = {
    "wait": _wait,
    "chat": _chat,
    "observe_entities": _observe_entities,
    "registry_search": _registry_search,
}

__all__ = ["CODECS"]
