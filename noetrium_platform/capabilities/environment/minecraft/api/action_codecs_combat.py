from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_codec_support import allowed, distance, error, integer, number, text


def _attack_nearest(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "attack_nearest"
    value = allowed(
        action_type,
        payload,
        {"entity", "query", "max_distance", "max_hits"},
    )
    name = value.get("entity", value.get("query", ""))
    result = {
        "entity": text(action_type, "entity", name),
        "max_distance": number(action_type, "max_distance", value.get("max_distance", 32)),
        "max_hits": integer(action_type, "max_hits", value.get("max_hits", 8), minimum=1, maximum=20),
    }
    if not 1 <= result["max_distance"] <= 128:
        raise error(action_type, "FIELD_RANGE", "max_distance must be in [1, 128]")
    return result


def _attack_entity(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "attack_entity"
    value = allowed(action_type, payload, {"entity_id", "max_distance", "max_hits"})
    return {
        "entity_id": integer(action_type, "entity_id", value.get("entity_id"), minimum=0, maximum=2**31 - 1),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=32),
        "max_hits": integer(action_type, "max_hits", value.get("max_hits", 12), minimum=1, maximum=40),
    }


def _attack_player(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "attack_player"
    value = allowed(action_type, payload, {"player", "max_distance", "max_hits"})
    return {
        "player": text(action_type, "player", value.get("player"), maximum=16),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=64),
        "max_hits": integer(action_type, "max_hits", value.get("max_hits", 20), minimum=1, maximum=40),
    }


def _ranged_attack(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "ranged_attack"
    value = allowed(
        action_type,
        payload,
        {"entity", "player", "max_distance", "shots"},
    )
    entity = value.get("player", value.get("entity"))
    return {
        "entity": text(action_type, "entity", entity),
        "max_distance": distance(action_type, "max_distance", value.get("max_distance"), default=48),
        "shots": integer(action_type, "shots", value.get("shots", 1), minimum=1, maximum=8),
    }


def _fire_projectile(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "fire_projectile"
    value = allowed(action_type, payload, {"weapon", "shots"})
    result: dict[str, Any] = {
        "shots": integer(
            action_type, "shots", value.get("shots", 1), minimum=1, maximum=8
        ),
    }
    weapon = value.get("weapon")
    if weapon is not None:
        normalized = text(action_type, "weapon", weapon)
        if normalized not in {"bow", "crossbow"}:
            raise error(action_type, "FIELD_ENUM", "weapon must be bow or crossbow")
        result["weapon"] = normalized
    return result


def _defend_self(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "defend_self"
    value = allowed(action_type, payload, {"radius", "max_targets", "max_hits"})
    return {
        "radius": distance(action_type, "radius", value.get("radius"), default=12, maximum=32),
        "max_targets": integer(action_type, "max_targets", value.get("max_targets", 4), minimum=1, maximum=16),
        "max_hits": integer(action_type, "max_hits", value.get("max_hits", 12), minimum=1, maximum=40),
    }


def _use_shield(payload: Mapping[str, Any]) -> dict[str, Any]:
    action_type = "use_shield"
    value = allowed(action_type, payload, {"duration_ms"})
    return {
        "duration_ms": integer(
            action_type, "duration_ms", value.get("duration_ms", 1200),
            minimum=100, maximum=10000,
        )
    }


CODECS = {
    "attack_nearest": _attack_nearest,
    "attack_entity": _attack_entity,
    "attack_player": _attack_player,
    "ranged_attack": _ranged_attack,
    "fire_projectile": _fire_projectile,
    "defend_self": _defend_self,
    "use_shield": _use_shield,
}

__all__ = ["CODECS"]
