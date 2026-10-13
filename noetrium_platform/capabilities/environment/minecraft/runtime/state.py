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


def _optional_name(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Minecraft {field_name} must be a non-empty string")
    return value.strip()


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Minecraft {field_name} must be boolean")
    return value


def _physical_state_snapshot(
    value: Any,
    field_name: str,
) -> dict[str, MinecraftJsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Minecraft {field_name} must be a mapping")
    if not value:
        return {}
    expected = {
        "velocity",
        "saturation",
        "oxygen",
        "on_ground",
        "time_since_on_ground",
        "in_water",
        "in_lava",
        "in_web",
        "collided_horizontally",
        "collided_vertically",
        "inventory_used",
        "pathfinder",
    }
    if set(value) != expected:
        raise ValueError(f"Minecraft {field_name} schema is invalid")
    velocity = minecraft_position(value["velocity"])
    if value["velocity"] is not None and velocity is None:
        raise ValueError(f"Minecraft {field_name}.velocity is invalid")
    pathfinder = value["pathfinder"]
    if not isinstance(pathfinder, Mapping) or set(pathfinder) != {
        "moving",
        "mining",
        "building",
    }:
        raise ValueError(f"Minecraft {field_name}.pathfinder is invalid")
    return {
        "velocity": velocity,
        "saturation": _optional_finite(value["saturation"], f"{field_name}.saturation"),
        "oxygen": _optional_finite(value["oxygen"], f"{field_name}.oxygen"),
        "on_ground": _optional_bool(value["on_ground"], f"{field_name}.on_ground"),
        "time_since_on_ground": _optional_finite(
            value["time_since_on_ground"],
            f"{field_name}.time_since_on_ground",
        ),
        "in_water": _optional_bool(value["in_water"], f"{field_name}.in_water"),
        "in_lava": _optional_bool(value["in_lava"], f"{field_name}.in_lava"),
        "in_web": _optional_bool(value["in_web"], f"{field_name}.in_web"),
        "collided_horizontally": _optional_bool(
            value["collided_horizontally"],
            f"{field_name}.collided_horizontally",
        ),
        "collided_vertically": _optional_bool(
            value["collided_vertically"],
            f"{field_name}.collided_vertically",
        ),
        "inventory_used": _optional_finite(
            value["inventory_used"],
            f"{field_name}.inventory_used",
        ),
        "pathfinder": {
            key: _optional_bool(pathfinder[key], f"{field_name}.pathfinder.{key}")
            for key in ("moving", "mining", "building")
        },
    }


def _surroundings_snapshot(value: Any, field_name: str) -> dict[str, MinecraftJsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Minecraft {field_name} must be a mapping")
    if not value:
        return {}
    expected = {
        "below",
        "legs",
        "head",
        "vertical_bounds",
        "first_solid_above_head",
        "surface",
    }
    if set(value) != expected:
        raise ValueError(f"Minecraft {field_name} schema is invalid")
    result: dict[str, MinecraftJsonValue] = {}
    for key in ("below", "legs", "head"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f"Minecraft {field_name}.{key} is invalid")
        result[key] = item
    bounds = value["vertical_bounds"]
    if bounds is not None:
        if (
            not isinstance(bounds, Mapping)
            or set(bounds) != {"min_y", "height", "max_y_exclusive"}
        ):
            raise ValueError(
                f"Minecraft {field_name}.vertical_bounds is invalid"
            )
        min_y = bounds["min_y"]
        height = bounds["height"]
        max_y_exclusive = bounds["max_y_exclusive"]
        if (
            isinstance(min_y, bool)
            or not isinstance(min_y, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
            or isinstance(max_y_exclusive, bool)
            or not isinstance(max_y_exclusive, int)
            or max_y_exclusive != min_y + height
        ):
            raise ValueError(
                f"Minecraft {field_name}.vertical_bounds is invalid"
            )
        result["vertical_bounds"] = {
            "min_y": min_y,
            "height": height,
            "max_y_exclusive": max_y_exclusive,
        }
    else:
        result["vertical_bounds"] = None

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

    surface = value["surface"]
    if surface is not None:
        if (
            not isinstance(surface, Mapping)
            or set(surface) != {"block", "block_y", "standing_position"}
        ):
            raise ValueError(f"Minecraft {field_name}.surface is invalid")
        block = surface["block"]
        block_y = surface["block_y"]
        standing = minecraft_position(surface["standing_position"])
        if (
            not isinstance(block, str)
            or not block.strip()
            or isinstance(block_y, bool)
            or not isinstance(block_y, int)
            or standing is None
        ):
            raise ValueError(f"Minecraft {field_name}.surface is invalid")
        result["surface"] = {
            "block": block,
            "block_y": block_y,
            "standing_position": standing,
        }
    else:
        result["surface"] = None
    return result


def _nearby_block_snapshot(value: Any, field_name: str) -> list[dict[str, MinecraftJsonValue]]:
    """Validate only bounded physical block witnesses from the live bridge."""
    if not isinstance(value, (list, tuple)) or len(value) > 12:
        raise ValueError(f"Minecraft {field_name} must be at most 12 visible blocks")
    result: list[dict[str, MinecraftJsonValue]] = []
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"name", "position", "distance"}:
            raise ValueError(f"Minecraft {field_name} block schema is invalid")
        name = row["name"]
        position = minecraft_position(row["position"])
        distance = _optional_finite(row["distance"], f"{field_name}.distance")
        if (
            not isinstance(name, str) or not name.strip()
            or position is None or distance is None or not 0 <= distance <= 16
        ):
            raise ValueError(f"Minecraft {field_name} block witness is invalid")
        result.append({"name": name, "position": position, "distance": distance})
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
    physical_state: dict[str, MinecraftJsonValue] = field(default_factory=dict)
    time_of_day: int | None = None
    weather: str | None = None
    biome: str | None = None
    surroundings: dict[str, MinecraftJsonValue] = field(default_factory=dict)
    nearby_blocks: list[dict[str, MinecraftJsonValue]] = field(default_factory=list)
    held_item: dict[str, MinecraftJsonValue] | None = None
    equipment: dict[str, MinecraftJsonValue] = field(default_factory=dict)
    dimension: str | None = None
    inventory: dict[str, int] = field(default_factory=dict)
    entities: dict[str, MinecraftEntityState] = field(default_factory=dict)
    anchors: dict[str, dict[str, float]] = field(default_factory=dict)
    deaths: int = 0
    last_effect_disposition: str | None = None
    last_action: dict[str, MinecraftJsonValue] | None = None
    last_outcome: dict[str, MinecraftJsonValue] | str | None = None
    last_event_sequence: int = 0
    # Transport-local fencing only.  This is intentionally omitted from compact
    # world checkpoints: restoring a session necessarily starts a new bridge
    # stream, while world truth remains unchanged.
    last_event_stream_id: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_entities < 1:
            raise ValueError("Minecraft state max_entities must be positive")

    def ingest(self, event: MinecraftObservationEvent) -> None:
        stream_id = event.stream_id
        if stream_id is not None and stream_id != self.last_event_stream_id:
            # A bridge recycle/restart creates a new sequence domain.  Reset only
            # transport ordering state; world projection and action evidence stay.
            self.last_event_stream_id = stream_id
            self.last_event_sequence = 0
        if event.sequence and event.sequence <= self.last_event_sequence:
            # Each stream sequence is an event identity. A duplicate death,
            # inventory change, or action result must never mutate the causal
            # state twice. The bridge starts a new sequence domain on recycle.
            raise ValueError(
                "Minecraft bridge event sequence is not strictly increasing: "
                f"{event.sequence} <= {self.last_event_sequence}"
            )
        self.last_event_sequence = max(self.last_event_sequence, event.sequence)
        payload = dict(event.payload)

        if event.kind in {"spawn_snapshot", "self_snapshot"}:
            self._ingest_self_snapshot(payload)
        elif event.kind == "health":
            if payload.get("health") is not None:
                self.health = _optional_finite(payload["health"], "health")
            if payload.get("food") is not None:
                self.food = _optional_finite(payload["food"], "food")
        elif event.kind == "entity_snapshot":
            rows = payload.get("entities")
            if not isinstance(rows, (list, tuple)):
                raise ValueError("Minecraft entity snapshot requires entity rows")
            if len(rows) > self.max_entities:
                raise ValueError("Minecraft entity snapshot exceeds authorized entity limit")
            # All-or-nothing indexed generation swap. Never expose half of a
            # corrupt observation batch to an Agent or a recovered session.
            fresh: dict[str, MinecraftEntityState] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("Minecraft entity snapshot contains invalid row")
                entity = MinecraftEntityState.from_observation(row)
                if entity is not None:
                    if entity.entity_id in fresh:
                        raise ValueError(
                            "Minecraft entity snapshot contains duplicate identity"
                        )
                    fresh[entity.entity_id] = entity
            self.entities = fresh
        elif event.kind == "death":
            self.deaths += 1
        elif event.kind == "action_result":
            action_id = payload.get("action_id")
            if not isinstance(action_id, str) or not action_id.strip():
                return
            raw_disposition = payload.get("effect_disposition")
            if raw_disposition not in {"applied", "rejected", "not_applied", "unknown"}:
                raise ValueError("Minecraft action_result effect disposition is invalid")
            self.last_effect_disposition = str(raw_disposition)
            action = payload.get("action")
            self.last_action = dict(action) if isinstance(action, Mapping) else None
            outcome = payload.get("outcome")
            self.last_outcome = dict(outcome) if isinstance(outcome, Mapping) else outcome
            control = payload.get("execution_control")
            if control is not None:
                if not isinstance(control, Mapping):
                    raise ValueError("Minecraft execution_control is invalid")
                if control.get("state") != "settled":
                    raise ValueError("Minecraft action control is not settled")
                if control.get("effect_disposition") != raw_disposition:
                    raise ValueError("Minecraft action control disagrees with effect evidence")
                if isinstance(self.last_outcome, Mapping):
                    self.last_outcome["execution_control"] = dict(control)

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
            self.health = _optional_finite(payload["health"], "health")
        if payload.get("food") is not None:
            self.food = _optional_finite(payload["food"], "food")
        if "physical_state" in payload:
            self.physical_state = _physical_state_snapshot(
                payload["physical_state"],
                "physical_state",
            )
        if "time_of_day" in payload:
            self.time_of_day = _optional_time_of_day(payload["time_of_day"], "time_of_day")
        if "weather" in payload:
            self.weather = _weather_snapshot(payload["weather"], "weather")
        if "biome" in payload:
            self.biome = _optional_name(payload["biome"], "biome")
        if "surroundings" in payload:
            self.surroundings = _surroundings_snapshot(payload["surroundings"], "surroundings")
        if "nearby_blocks" in payload:
            self.nearby_blocks = _nearby_block_snapshot(payload["nearby_blocks"], "nearby_blocks")
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

        raw_inventory = payload.get("inventory", ()) or ()
        if not isinstance(raw_inventory, (list, tuple)):
            raise ValueError("Minecraft inventory observation must contain item rows")
        inventory: dict[str, int] = {}
        for item in raw_inventory:
            if not isinstance(item, Mapping):
                raise ValueError("Minecraft inventory observation contains invalid row")
            raw_name = item.get("name")
            count = item.get("count", 0)
            if (
                not isinstance(raw_name, str)
                or not raw_name.strip()
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError("Minecraft inventory observation row is invalid")
            name = raw_name.strip()
            inventory[name] = inventory.get(name, 0) + count
        self.inventory = inventory

    def anchor(self, name: str) -> dict[str, float] | None:
        value = self.anchors.get(name)
        return dict(value) if value else None

    def set_anchor(self, name: str, position: Mapping[str, Any] | None = None) -> None:
        if not name.strip():
            raise ValueError("Minecraft anchor name must be non-empty")
        resolved = minecraft_position(position) if position is not None else self.position
        if resolved is not None:
            self.anchors[name] = resolved

    def decision_view(
        self,
        *,
        detailed_entities: bool = False,
        include_entities: bool = True,
        snapshot_state: Mapping[str, MinecraftJsonValue] | None = None,
    ) -> dict[str, MinecraftJsonValue]:
        """Compile the Minecraft-only model-facing state.

        The authoritative compact state remains lossless and checkpointable.
        Normal planning sees entity counts, the nearest representative of each
        entity label, and every visible player. An explicit observe_entities
        action may request the full columnar table. This mirrors mature
        Minecraft agents: rich evidence is retained, but routine LLM context
        contains only decision-relevant world state.
        """

        # The caller that already materialized the exact canonical physical
        # snapshot can project it without a second O(entities + inventory)
        # walk. Work on an independent outer mapping: the decision projection
        # drops audit sequence and replaces entity rows.
        state = self.compact() if snapshot_state is None else dict(snapshot_state)
        if not include_entities:
            state.pop("nearby_entities", None)
            state.pop("last_event_sequence", None)
            return state

        nearby = state.get("nearby_entities")
        counts: dict[str, int] = {}
        all_rows: list[list[MinecraftJsonValue]] = []
        nearest_by_label: dict[str, tuple[float, list[MinecraftJsonValue]]] = {}
        player_rows: list[list[MinecraftJsonValue]] = []

        if isinstance(nearby, list):
            for raw in nearby:
                if not isinstance(raw, Mapping):
                    continue
                username = raw.get("username")
                name = raw.get("name")
                mob_type = raw.get("mob_type")
                entity_type = raw.get("type")
                label = str(
                    name or mob_type or entity_type or username or "unknown"
                )
                counts[label] = counts.get(label, 0) + 1

                position = raw.get("position")
                if isinstance(position, Mapping):
                    x = position.get("x")
                    y = position.get("y")
                    z = position.get("z")
                else:
                    x = y = z = None

                row: list[MinecraftJsonValue] = [
                    raw.get("runtime_id"),
                    username,
                    name,
                    mob_type,
                    entity_type,
                    raw.get("distance"),
                    x,
                    y,
                    z,
                ]
                all_rows.append(row)

                distance_raw = raw.get("distance")
                distance = (
                    float(distance_raw)
                    if isinstance(distance_raw, (int, float))
                    and not isinstance(distance_raw, bool)
                    else float("inf")
                )
                if username is not None or entity_type == "player":
                    player_rows.append(row)
                previous = nearest_by_label.get(label)
                if previous is None or distance < previous[0]:
                    nearest_by_label[label] = (distance, row)

        if detailed_entities:
            rows = all_rows
            mode = "detailed"
        else:
            rows = [
                pair[1]
                for _, pair in sorted(nearest_by_label.items())
            ]
            seen = {
                (row[0], row[1], row[2], row[3], row[4])
                for row in rows
            }
            for row in player_rows:
                identity = (row[0], row[1], row[2], row[3], row[4])
                if identity not in seen:
                    rows.append(row)
                    seen.add(identity)
            mode = "summary"

        state.pop("last_event_sequence", None)
        state["nearby_entities"] = {
            "mode": mode,
            "counts": dict(sorted(counts.items())),
            "columns": [
                "runtime_id",
                "username",
                "name",
                "mob_type",
                "type",
                "distance",
                "x",
                "y",
                "z",
            ],
            "rows": rows,
        }
        return state

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
            "physical_state": dict(self.physical_state),
            "time_of_day": self.time_of_day,
            "weather": self.weather,
            "biome": self.biome,
            "surroundings": dict(self.surroundings),
            "nearby_blocks": [dict(row) for row in self.nearby_blocks],
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
            "last_effect_disposition": self.last_effect_disposition,
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
            "physical_state",
            "time_of_day",
            "weather",
            "biome",
            "surroundings",
            "nearby_blocks",
            "held_item",
            "equipment",
            "dimension",
            "inventory",
            "nearby_entities",
            "anchors",
            "deaths",
            "last_effect_disposition",
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
        physical_state = _physical_state_snapshot(
            document["physical_state"],
            "checkpoint physical_state",
        )
        time_of_day = _optional_time_of_day(document["time_of_day"], "checkpoint time_of_day")
        weather = _weather_snapshot(document["weather"], "checkpoint weather")
        biome = _optional_name(document["biome"], "checkpoint biome")
        surroundings = _surroundings_snapshot(document["surroundings"], "checkpoint surroundings")
        nearby_blocks = _nearby_block_snapshot(document["nearby_blocks"], "checkpoint nearby_blocks")
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
        last_disposition = document["last_effect_disposition"]
        if last_disposition is not None and last_disposition not in {
            "applied",
            "rejected",
            "not_applied",
            "unknown",
        }:
            raise ValueError("Minecraft state checkpoint effect disposition is invalid")
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
            physical_state=physical_state,
            time_of_day=time_of_day,
            weather=weather,
            biome=biome,
            surroundings=surroundings,
            nearby_blocks=nearby_blocks,
            held_item=held_item,
            equipment=equipment,
            dimension=dimension,
            inventory=inventory,
            entities=entities,
            anchors=anchors,
            deaths=deaths,
            last_effect_disposition=last_disposition,
            last_action=None if last_action is None else dict(last_action),
            last_outcome=(
                dict(last_outcome) if isinstance(last_outcome, Mapping) else last_outcome
            ),
            last_event_sequence=last_sequence,
        )

    def snapshot_with_digest(self) -> tuple[dict[str, MinecraftJsonValue], str]:
        # One grounded materialization is shared by both the exported snapshot
        # and its exact canonical digest. Never hash a second observation of
        # a mutable world projection.
        snapshot = self.compact()
        return snapshot, canonical_digest(snapshot)

    def snapshot_digest(self) -> str:
        return self.snapshot_with_digest()[1]


__all__ = ["MinecraftStateProjection"]
