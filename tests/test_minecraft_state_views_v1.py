from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftObservationEvent
from noetrium_platform.capabilities.environment.minecraft.runtime import (
    MinecraftEntityState,
    MinecraftStateProjection,
)


def _state_with_entity() -> MinecraftStateProjection:
    state = MinecraftStateProjection(max_entities=4)
    state.ingest(
        MinecraftObservationEvent(
            "entity_observation",
            {
                "uuid": "entity-1",
                "name": "zombie",
                "mob_type": "zombie",
                "type": "mob",
                "position": {"x": 1, "y": 64, "z": -2},
                "distance": 3.5,
                "ignored": "provider-only-detail",
            },
            sequence=1,
        )
    )
    return state


def test_self_snapshot_preserves_native_pose_and_equipment_across_checkpoint() -> None:
    state = MinecraftStateProjection(max_entities=4)
    state.ingest(
        MinecraftObservationEvent(
            "self_snapshot",
            {
                "username": "bot",
                "position": {"x": 1, "y": 64, "z": 3},
                "yaw": 1.25,
                "pitch": -0.5,
                "health": 20,
                "food": 18,
                "held_item": {"name": "iron_pickaxe", "count": 1, "slot": 36},
                "equipment": {
                    "hand": {"name": "iron_pickaxe", "count": 1, "slot": 36},
                    "off_hand": None,
                    "feet": None,
                    "legs": None,
                    "torso": None,
                    "head": None,
                },
                "inventory": [{"name": "oak_log", "count": 3}],
                "dimension": "overworld",
            },
            sequence=1,
        )
    )

    compact = state.compact()
    assert compact["yaw"] == 1.25
    assert compact["pitch"] == -0.5
    assert compact["held_item"]["name"] == "iron_pickaxe"
    assert compact["equipment"]["hand"]["name"] == "iron_pickaxe"

    restored = MinecraftStateProjection.from_compact(compact, max_entities=4)
    assert restored.compact() == compact


def test_entity_state_is_frozen_and_projection_owns_typed_rows() -> None:
    state = _state_with_entity()
    entity = state.entities["entity-1"]

    assert isinstance(entity, MinecraftEntityState)
    assert entity.entity_id == "entity-1"
    assert entity.name == "zombie"
    with pytest.raises(FrozenInstanceError):
        entity.name = "mutated"  # type: ignore[misc]


def test_entity_compact_preserves_public_json_shape() -> None:
    state = _state_with_entity()

    assert state.compact()["nearby_entities"] == [
        {
            "id": "entity-1",
            "name": "zombie",
            "mob_type": "zombie",
            "type": "mob",
            "position": {"x": 1.0, "y": 64.0, "z": -2.0},
            "distance": 3.5,
        }
    ]


def test_compact_round_trip_restores_typed_entity_and_digest() -> None:
    state = _state_with_entity()
    compact = state.compact()

    restored = MinecraftStateProjection.from_compact(compact, max_entities=4)

    assert isinstance(restored.entities["entity-1"], MinecraftEntityState)
    assert restored.compact() == compact
    assert restored.snapshot_digest() == state.snapshot_digest()


def test_restore_rejects_duplicate_entity_identity() -> None:
    state = _state_with_entity()
    compact = state.compact()
    compact["nearby_entities"] = [
        compact["nearby_entities"][0],
        dict(compact["nearby_entities"][0]),
    ]

    with pytest.raises(ValueError, match="entity identity"):
        MinecraftStateProjection.from_compact(compact, max_entities=4)


def test_restore_rejects_invalid_entity_position_and_distance() -> None:
    compact = _state_with_entity().compact()
    compact["nearby_entities"][0]["position"] = {"x": 1, "y": 2}
    with pytest.raises(ValueError, match="entity position"):
        MinecraftStateProjection.from_compact(compact, max_entities=4)

    compact = _state_with_entity().compact()
    compact["nearby_entities"][0]["distance"] = True
    with pytest.raises(ValueError, match="entity distance"):
        MinecraftStateProjection.from_compact(compact, max_entities=4)


def test_live_entity_numeric_fields_are_normalized_and_fail_closed() -> None:
    state = _state_with_entity()
    entity = state.entities["entity-1"]
    assert entity.position == {"x": 1.0, "y": 64.0, "z": -2.0}
    assert entity.distance == 3.5

    invalid = MinecraftStateProjection()
    with pytest.raises(ValueError, match="observation position"):
        invalid.ingest(
            MinecraftObservationEvent(
                "entity_observation",
                {"uuid": "bad-position", "position": {"x": 1, "y": 2}},
                sequence=1,
            )
        )
    with pytest.raises(ValueError, match="observation distance"):
        invalid.ingest(
            MinecraftObservationEvent(
                "entity_observation",
                {"uuid": "bad-distance", "distance": True},
                sequence=2,
            )
        )
