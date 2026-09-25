from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from ..api import MinecraftJsonValue


def minecraft_position(value: object) -> dict[str, float] | None:
    """Normalize one finite xyz position without accepting ambiguous shapes."""

    if not isinstance(value, Mapping):
        return None
    if not all(key in value for key in ("x", "y", "z")):
        return None
    if any(isinstance(value[key], bool) for key in ("x", "y", "z")):
        return None
    try:
        position = {key: float(value[key]) for key in ("x", "y", "z")}
    except (TypeError, ValueError):
        return None
    return position if all(math.isfinite(item) for item in position.values()) else None


@dataclass(frozen=True, slots=True)
class MinecraftEntityState:
    """Typed bounded entity row used by the Minecraft state projection."""

    entity_id: str
    name: MinecraftJsonValue = None
    mob_type: MinecraftJsonValue = None
    entity_type: MinecraftJsonValue = None
    position: MinecraftJsonValue = None
    distance: MinecraftJsonValue = None

    @classmethod
    def from_observation(
        cls, payload: Mapping[str, MinecraftJsonValue]
    ) -> "MinecraftEntityState | None":
        entity_id = str(
            payload.get("uuid")
            or payload.get("id")
            or payload.get("username")
            or payload.get("name")
            or ""
        )
        if not entity_id:
            return None
        entity_position = payload.get("position")
        if entity_position is not None:
            parsed_position = minecraft_position(entity_position)
            if parsed_position is None:
                raise ValueError("Minecraft entity observation position is invalid")
            entity_position = parsed_position
        distance_value = payload.get("distance")
        if distance_value is not None:
            if (
                isinstance(distance_value, bool)
                or not isinstance(distance_value, (int, float))
                or not math.isfinite(float(distance_value))
            ):
                raise ValueError("Minecraft entity observation distance is invalid")
            distance_value = float(distance_value)
        return cls(
            entity_id=entity_id,
            name=payload.get("name"),
            mob_type=payload.get("mob_type"),
            entity_type=payload.get("type"),
            position=entity_position,
            distance=distance_value,
        )

    def compact(self) -> dict[str, MinecraftJsonValue]:
        return {
            "id": self.entity_id,
            "name": self.name,
            "mob_type": self.mob_type,
            "type": self.entity_type,
            "position": self.position,
            "distance": self.distance,
        }

    @classmethod
    def from_compact(cls, row: Mapping[str, MinecraftJsonValue]) -> "MinecraftEntityState":
        entity_id = str(row.get("id", ""))
        if not entity_id.strip():
            raise ValueError("Minecraft state checkpoint entity identity is invalid")
        entity_position = row.get("position")
        if entity_position is not None:
            parsed_position = minecraft_position(entity_position)
            if parsed_position is None:
                raise ValueError("Minecraft state checkpoint entity position is invalid")
            entity_position = parsed_position
        distance_value = row.get("distance")
        if distance_value is not None:
            if (
                isinstance(distance_value, bool)
                or not isinstance(distance_value, (int, float))
                or not math.isfinite(float(distance_value))
            ):
                raise ValueError("Minecraft state checkpoint entity distance is invalid")
            distance_value = float(distance_value)
        return cls(
            entity_id=entity_id,
            name=row.get("name"),
            mob_type=row.get("mob_type"),
            entity_type=row.get("type"),
            position=entity_position,
            distance=distance_value,
        )


__all__ = ["MinecraftEntityState", "minecraft_position"]
