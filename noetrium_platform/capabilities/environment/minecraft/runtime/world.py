from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from ..api.contracts import MinecraftJsonValue
from .multi_pattern import SubstringAggregatePlan


@dataclass(frozen=True, slots=True)
class MinecraftEntityMatch:
    entity: Mapping[str, MinecraftJsonValue]
    distance: float


class MinecraftWorldQuery:
    """Pure queries over the rich observation; never calls the server."""

    @staticmethod
    def inventory_count(state: Mapping[str, MinecraftJsonValue], item: str) -> int:
        inventory = state.get("inventory")
        if not isinstance(inventory, Mapping):
            return 0
        needle = item.strip().lower()
        if not needle:
            return 0
        return sum(
            int(value)
            for key, value in inventory.items()
            if str(key).strip().lower() == needle
        )

    @staticmethod
    def nearest_entity(state: Mapping[str, MinecraftJsonValue], query: str = "") -> MinecraftEntityMatch | None:
        entities = state.get("nearby_entities")
        position = state.get("position")
        if not isinstance(entities, (list, tuple)) or not isinstance(position, Mapping):
            return None
        needle = query.lower()
        best_entity: Mapping[str, MinecraftJsonValue] | None = None
        best_distance_squared: float | None = None
        try:
            px = float(position["x"])
            py = float(position["y"])
            pz = float(position["z"])
        except (KeyError, TypeError, ValueError):
            return None
        for entity in entities:
            if not isinstance(entity, Mapping):
                continue
            if needle:
                haystack = " ".join(
                    str(entity.get(key, ""))
                    for key in ("name", "type", "mob_type", "username")
                ).lower()
                if needle not in haystack:
                    continue
            entity_position = entity.get("position")
            if not isinstance(entity_position, Mapping):
                continue
            try:
                dx = px - float(entity_position["x"])
                dy = py - float(entity_position["y"])
                dz = pz - float(entity_position["z"])
            except (KeyError, TypeError, ValueError):
                continue
            distance_squared = dx * dx + dy * dy + dz * dz
            if best_distance_squared is None or distance_squared < best_distance_squared:
                best_entity = entity
                best_distance_squared = distance_squared
        if best_entity is None or best_distance_squared is None:
            return None
        return MinecraftEntityMatch(best_entity, math.sqrt(best_distance_squared))

    @staticmethod
    def blocks_matching(
        state: Mapping[str, MinecraftJsonValue],
        query: str,
        *,
        limit: int = 32,
    ) -> tuple[Mapping[str, MinecraftJsonValue], ...]:
        if limit < 1:
            raise ValueError("world block query limit must be positive")
        blocks = state.get("nearby_blocks")
        if not isinstance(blocks, (list, tuple)):
            return ()
        needle = query.lower()
        selected: list[Mapping[str, MinecraftJsonValue]] = []
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            if needle not in str(block.get("name", block.get("block", ""))).lower():
                continue
            selected.append(block)
            if len(selected) >= limit:
                break
        return tuple(selected)

    @staticmethod
    def is_safe(state: Mapping[str, MinecraftJsonValue], *, minimum_health: float = 6.0) -> bool:
        try:
            health = float(state.get("health", 0))
        except (TypeError, ValueError):
            return False
        hostiles = state.get("hostile_entities", ())
        return health >= minimum_health and not bool(hostiles)

    @staticmethod
    def resource_summary(state: Mapping[str, MinecraftJsonValue], items: tuple[str, ...]) -> Mapping[str, int]:
        inventory = state.get("inventory")
        if not isinstance(inventory, Mapping):
            return {item: 0 for item in items}
        return SubstringAggregatePlan.compile(items).aggregate(inventory)


@dataclass(frozen=True, slots=True)
class MinecraftRoutine:
    routine_id: str
    objective: str
    min_time: int
    max_time: int
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.routine_id.strip() or not self.objective.strip() or not 0 <= self.min_time <= self.max_time <= 24000:
            raise ValueError("Minecraft routine time window is invalid")


class MinecraftRoutineController:
    """Selects persistent day/night NPC-style objectives from world time."""

    def __init__(self, routines: tuple[MinecraftRoutine, ...]) -> None:
        if not routines:
            raise ValueError("Minecraft routine controller requires routines")
        if len({routine.routine_id for routine in routines}) != len(routines):
            raise ValueError("Minecraft routine ids must be unique")
        self._routines = routines

    def active(self, state: Mapping[str, MinecraftJsonValue]) -> MinecraftRoutine | None:
        try:
            time_of_day = int(state.get("time_of_day", state.get("time", 0))) % 24000
        except (TypeError, ValueError):
            return None
        best: MinecraftRoutine | None = None
        best_key: tuple[int, str] | None = None
        for routine in self._routines:
            if not (routine.min_time <= time_of_day <= routine.max_time):
                continue
            key = (routine.priority, routine.routine_id)
            if best_key is None or key > best_key:
                best = routine
                best_key = key
        return best


__all__ = ["MinecraftEntityMatch", "MinecraftRoutine", "MinecraftRoutineController", "MinecraftWorldQuery"]
