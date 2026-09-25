from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import MinecraftJsonValue, MinecraftObservationEvent


from .state_views import MinecraftEntityState, minecraft_position


def _optional_finite(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Minecraft {field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Minecraft {field_name} must be finite")
    return parsed


def _item_snapshot(value: Any, field_name: str) -> dict[str, MinecraftJsonValue] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"Minecraft {field_name} must be an item mapping")
    return {str(key): item for key, item in value.items()}


def _optional_time_of_day(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Minecraft {field_name} must be an integer")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Minecraft {field_name} must be an integer") from None
    if not math.isfinite(parsed) or parsed != int(parsed) or not 0 <= int(parsed) < 24000:
        raise ValueError(f"Minecraft {field_name} must be in [0, 24000)")
    return int(parsed)


def _weather_snapshot(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {"clear", "rain", "thunder"}:
        raise ValueError(f"Minecraft {field_name} is invalid")
    return value


def _surroundings_snapshot(value: Any, field_name: str) -> dict[str, MinecraftJsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Minecraft {field_name} must be a mapping")
    if not value:
        return {}
    expected = {"below", "legs", "head", "first_solid_above_head"}
    if set(value) != expected:
        raise ValueError(f"Minecraft {field_name} schema is invalid")
    result: dict[str, MinecraftJsonValue] = {}
    for key in ("below", "legs", "head"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f"Minecraft {field_name}.{key} is invalid")
        result[key] = item
    first = value["first_solid_above_head"]
    if first is not None:
        if not isinstance(first, Mapping) or set(first) != {"name", "blocks_up"}:
            raise ValueError(f"Minecraft {field_name}.first_solid_above_head is invalid")
        name = first["name"]
        blocks_up = first["blocks_up"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or isinstance(blocks_up, bool)
            or not isinstance(blocks_up, int)
            or blocks_up < 0
        ):
            raise ValueError(f"Minecraft {field_name}.first_solid_above_head is invalid")
        result["first_solid_above_head"] = {"name": name, "blocks_up": blocks_up}
    else:
        result["first_solid_above_head"] = None
    return result


@dataclass(slots=True)
class MinecraftStateProjection:
    """Deterministic read model reduced from grounded bridge observations.

    This is a Minecraft environment projection, not a memory store. It keeps
    only the latest bounded world-facing state needed by an environment
    session, while preserving action verification and death observations for
    reconciliation diagnostics.
    """

    max_entities: int = 256
    username: str = ""
    position: dict[str, float] | None = None
    yaw: float | None = None
    pitch: float | None = None
    health: float | None = None
    food: float | None = None
    time_of_day: int | None = None
    weather: str | None = None
    surroundings: dict[str, MinecraftJsonValue] = field(default_factory=dict)
    held_item: dict[str, MinecraftJsonValue] | None = None
    equipment: dict[str, MinecraftJsonValue] = field(default_factory=dict)
    dimension: str | None = None
    inventory: dict[str, int] = field(default_factory=dict)
    entities: dict[str, MinecraftEntityState] = field(default_factory=dict)
    anchors: dict[str, dict[str, float]] = field(default_factory=dict)
    deaths: int = 0
    last_action_verified: bool | None = None
    last_action: dict[str, MinecraftJsonValue] | None = None
    last_outcome: dict[str, MinecraftJsonValue] | str | None = None
    last_event_sequence: int = 0

    def __post_init__(self) -> None:
        if self.max_entities < 1:
            raise ValueError("Minecraft state max_entities must be positive")

    def ingest(self, event: MinecraftObservationEvent) -> None:
        if event.sequence and event.sequence < self.last_event_sequence:
            raise ValueError(
                "Minecraft bridge event sequence regressed: "
                f"{event.sequence} < {self.last_event_sequence}"
            )
        self.last_event_sequence = max(self.last_event_sequence, event.sequence)
        payload = dict(event.payload)

        if event.kind in {"spawn_snapshot", "self_snapshot"}:
            self._ingest_self_snapshot(payload)
        elif event.kind == "health":
            if payload.get("health") is not None:
                self.health = float(payload["health"])
            if payload.get("food") is not None:
                self.food = float(payload["food"])
        elif event.kind == "entity_observation":
            self._ingest_entity(payload)
        elif event.kind == "death":
            self.deaths += 1
        elif event.kind == "action_result":
            action_id = payload.get("action_id")
            if not isinstance(action_id, str) or not action_id.strip():
                return
            verified = payload.get("verified")
            if not isinstance(verified, bool):
                raise ValueError("Minecraft action_result verified must be boolean")
            self.last_action_verified = verified
            action = payload.get("action")
            self.last_action = dict(action) if isinstance(action, Mapping) else None
            outcome = payload.get("outcome")
            self.last_outcome = dict(outcome) if isinstance(outcome, Mapping) else outcome

    def _ingest_self_snapshot(self, payload: Mapping[str, Any]) -> None:
        self.username = str(payload.get("username") or self.username)
        position = minecraft_position(payload.get("position"))
        if position is not None:
            self.position = position
            self.anchors.setdefault("spawn", dict(position))
        if "yaw" in payload:
            self.yaw = _optional_finite(payload["yaw"], "yaw")
        if "pitch" in payload:
            self.pitch = _optional_finite(payload["pitch"], "pitch")
        if payload.get("health") is not None:
            self.health = float(payload["health"])
        if payload.get("food") is not None:
            self.food = float(payload["food"])
        if "time_of_day" in payload:
            self.time_of_day = _optional_time_of_day(payload["time_of_day"], "time_of_day")
        if "weather" in payload:
            self.weather = _weather_snapshot(payload["weather"], "weather")
        if "surroundings" in payload:
            self.surroundings = _surroundings_snapshot(payload["surroundings"], "surroundings")
        if "held_item" in payload:
            self.held_item = _item_snapshot(payload["held_item"], "held_item")
        if "equipment" in payload:
            equipment = payload["equipment"]
            if not isinstance(equipment, Mapping):
                raise ValueError("Minecraft equipment must be a mapping")
            self.equipment = {
                str(slot): item
                for slot, item in equipment.items()
                if _item_snapshot(item, f"equipment[{slot!r}]") is not None
            }
            self.equipment.update({
                str(slot): None
                for slot, item in equipment.items()
                if item is None
            })
        if payload.get("dimension") is not None:
            self.dimension = str(payload["dimension"])

        inventory: dict[str, int] = {}
        for item in payload.get("inventory", ()) or ():
            if not isinstance(item, Mapping) or not item.get("name"):
                continue
            name = str(item["name"])
            inventory[name] = inventory.get(name, 0) + int(item.get("count", 0))
        self.inventory = inventory

    def _ingest_entity(self, payload: Mapping[str, MinecraftJsonValue]) -> None:
        entity = MinecraftEntityState.from_observation(payload)
        if entity is None:
            return
        self.entities[entity.entity_id] = entity
        while len(self.entities) > self.max_entities:
            self.entities.pop(next(iter(self.entities)))

    def replace_entities(self) -> None:
        """Start a fresh entity-observation generation.

        Entity observations are a bounded current-state projection.  Keeping
        rows from a previous scan makes absence indistinguishable from
        presence and contaminates task-level success predicates.
        """

        self.entities.clear()

    def anchor(self, name: str) -> dict[str, float] | None:
        value = self.anchors.get(name)
        return dict(value) if value else None

    def set_anchor(self, name: str, position: Mapping[str, Any] | None = None) -> None:
        if not name.strip():
            raise ValueError("Minecraft anchor name must be non-empty")
        resolved = minecraft_position(position) if position is not None else self.position
        if resolved is not None:
            self.anchors[name] = resolved

    def compact(self) -> dict[str, MinecraftJsonValue]:
        entities = [
            value.compact()
            for _, value in sorted(self.entities.items())
        ]
        return {
            "username": self.username,
            "position": dict(self.position) if self.position else None,
            "yaw": self.yaw,
            "pitch": self.pitch,
            "health": self.health,
            "food": self.food,
            "time_of_day": self.time_of_day,
            "weather": self.weather,
            "surroundings": dict(self.surroundings),
            "held_item": dict(self.held_item) if self.held_item else None,
            "equipment": {
                key: (dict(value) if isinstance(value, Mapping) else value)
                for key, value in sorted(self.equipment.items())
            },
            "dimension": self.dimension,
            "inventory": dict(sorted(self.inventory.items())),
            "nearby_entities": entities,
            "anchors": {
                key: dict(value) for key, value in sorted(self.anchors.items())
            },
            "deaths": self.deaths,
            "last_action_verified": self.last_action_verified,
            "last_action": dict(self.last_action) if self.last_action else None,
            "last_outcome": (
                dict(self.last_outcome)
                if isinstance(self.last_outcome, Mapping)
                else self.last_outcome
            ),
            "last_event_sequence": self.last_event_sequence,
        }

    @classmethod
    def from_compact(
        cls,
        document: Mapping[str, Any],
        *,
        max_entities: int,
    ) -> "MinecraftStateProjection":
        """Validate and rebuild an exact compact projection before live restore."""

        expected = {
            "username",
            "position",
            "yaw",
            "pitch",
            "health",
            "food",
            "time_of_day",
            "weather",
            "surroundings",
            "held_item",
            "equipment",
            "dimension",
            "inventory",
            "nearby_entities",
            "anchors",
            "deaths",
            "last_action_verified",
            "last_action",
            "last_outcome",
            "last_event_sequence",
        }
        if set(document) != expected:
            raise ValueError(
                "Minecraft state checkpoint schema mismatch: "
                f"missing={sorted(expected - set(document))!r} "
                f"unknown={sorted(set(document) - expected)!r}"
            )
        position = None if document["position"] is None else minecraft_position(document["position"])
        if document["position"] is not None and position is None:
            raise ValueError("Minecraft state checkpoint position is invalid")
        yaw = _optional_finite(document["yaw"], "checkpoint yaw")
        pitch = _optional_finite(document["pitch"], "checkpoint pitch")
        if isinstance(document["health"], bool) or isinstance(document["food"], bool):
            raise ValueError("Minecraft state checkpoint health/food is invalid")
        health = None if document["health"] is None else float(document["health"])
        food = None if document["food"] is None else float(document["food"])
        if any(value is not None and not math.isfinite(value) for value in (health, food)):
            raise ValueError("Minecraft state checkpoint health/food is non-finite")
        time_of_day = _optional_time_of_day(document["time_of_day"], "checkpoint time_of_day")
        weather = _weather_snapshot(document["weather"], "checkpoint weather")
        surroundings = _surroundings_snapshot(document["surroundings"], "checkpoint surroundings")
        held_item = _item_snapshot(document["held_item"], "checkpoint held_item")
        equipment_raw = document["equipment"]
        if not isinstance(equipment_raw, Mapping):
            raise ValueError("Minecraft state checkpoint equipment is invalid")
        equipment = {
            str(slot): item
            for slot, item in equipment_raw.items()
            if _item_snapshot(item, f"checkpoint equipment[{slot!r}]") is not None
        }
        equipment.update({
            str(slot): None
            for slot, item in equipment_raw.items()
            if item is None
        })
        inventory_raw = document["inventory"]
        if not isinstance(inventory_raw, Mapping):
            raise ValueError("Minecraft state checkpoint inventory is invalid")
        inventory: dict[str, int] = {}
        for name, count in inventory_raw.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError("Minecraft state checkpoint inventory row is invalid")
            inventory[name] = count
        anchors_raw = document["anchors"]
        if not isinstance(anchors_raw, Mapping):
            raise ValueError("Minecraft state checkpoint anchors are invalid")
        anchors: dict[str, dict[str, float]] = {}
        for name, value in anchors_raw.items():
            parsed = minecraft_position(value)
            if not isinstance(name, str) or not name.strip() or parsed is None:
                raise ValueError("Minecraft state checkpoint anchor row is invalid")
            anchors[name] = parsed
        entities_raw = document["nearby_entities"]
        if not isinstance(entities_raw, list) or len(entities_raw) > max_entities:
            raise ValueError("Minecraft state checkpoint entity rows are invalid")
        entities: dict[str, MinecraftEntityState] = {}
        for row in entities_raw:
            if not isinstance(row, Mapping):
                raise ValueError("Minecraft state checkpoint entity row is invalid")
            entity = MinecraftEntityState.from_compact(row)
            if entity.entity_id in entities:
                raise ValueError("Minecraft state checkpoint entity identity is invalid")
            entities[entity.entity_id] = entity
        deaths = document["deaths"]
        last_sequence = document["last_event_sequence"]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (deaths, last_sequence)
        ):
            raise ValueError("Minecraft state checkpoint counters are invalid")
        last_verified = document["last_action_verified"]
        if last_verified is not None and not isinstance(last_verified, bool):
            raise ValueError("Minecraft state checkpoint action verification is invalid")
        last_action = document["last_action"]
        if last_action is not None and not isinstance(last_action, Mapping):
            raise ValueError("Minecraft state checkpoint last action is invalid")
        last_outcome = document["last_outcome"]
        if last_outcome is not None and not isinstance(last_outcome, (Mapping, str)):
            raise ValueError("Minecraft state checkpoint last outcome is invalid")
        username = document["username"]
        dimension = document["dimension"]
        if not isinstance(username, str) or (
            dimension is not None and not isinstance(dimension, str)
        ):
            raise ValueError("Minecraft state checkpoint text fields are invalid")
        return cls(
            max_entities=max_entities,
            username=username,
            position=position,
            yaw=yaw,
            pitch=pitch,
            health=health,
            food=food,
            time_of_day=time_of_day,
            weather=weather,
            surroundings=surroundings,
            held_item=held_item,
            equipment=equipment,
            dimension=dimension,
            inventory=inventory,
            entities=entities,
            anchors=anchors,
            deaths=deaths,
            last_action_verified=last_verified,
            last_action=None if last_action is None else dict(last_action),
            last_outcome=(
                dict(last_outcome) if isinstance(last_outcome, Mapping) else last_outcome
            ),
            last_event_sequence=last_sequence,
        )

    def snapshot_digest(self) -> str:
        return canonical_digest(self.compact())


__all__ = ["MinecraftStateProjection"]
