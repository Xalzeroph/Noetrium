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
            "entity_snapshot",
            {"entities": [{
                "uuid": "entity-1",
                "id": 42,
                "username": "zed",
                "name": "zombie",
                "mob_type": "zombie",
                "type": "mob",
                "position": {"x": 1, "y": 64, "z": -2},
                "distance": 3.5,
                "ignored": "provider-only-detail",
            }]},
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
                "physical_state": {
                    "velocity": {"x": 0.1, "y": 0.0, "z": -0.2},
                    "saturation": 5.0,
                    "oxygen": 20.0,
                    "on_ground": True,
                    "time_since_on_ground": 0.0,
                    "in_water": False,
                    "in_lava": False,
                    "in_web": False,
                    "collided_horizontally": True,
                    "collided_vertically": False,
                    "inventory_used": 7.0,
                    "pathfinder": {
                        "moving": True,
                        "mining": False,
                        "building": False,
                    },
                },
                "time_of_day": 7000,
                "weather": "rain",
                "biome": "plains",
                "surroundings": {
                    "below": "grass_block",
                    "legs": "air",
                    "head": "air",
                    "vertical_bounds": {
                        "min_y": -64,
                        "height": 384,
                        "max_y_exclusive": 320,
                    },
                    "first_solid_above_head": {"name": "oak_leaves", "blocks_up": 4},
                    "surface": {
                        "block": "grass_block",
                        "block_y": 64,
                        "standing_position": {"x": 0.5, "y": 65.0, "z": 0.5},
                    },
                },
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
    assert compact["physical_state"]["velocity"]["x"] == 0.1
    assert compact["physical_state"]["collided_horizontally"] is True
    assert compact["physical_state"]["pathfinder"]["moving"] is True
    assert compact["time_of_day"] == 7000
    assert compact["weather"] == "rain"
    assert compact["biome"] == "plains"
    assert compact["surroundings"]["first_solid_above_head"]["name"] == "oak_leaves"
    assert compact["surroundings"]["vertical_bounds"]["max_y_exclusive"] == 320
    assert compact["surroundings"]["surface"]["standing_position"]["y"] == 65.0
    assert compact["held_item"]["name"] == "iron_pickaxe"
    assert compact["equipment"]["hand"]["name"] == "iron_pickaxe"

    restored = MinecraftStateProjection.from_compact(compact, max_entities=4)
    assert restored.compact() == compact


def test_nearby_block_sensing_is_bounded_grounded_and_checkpoint_durable() -> None:
    state = MinecraftStateProjection(max_entities=4)
    state.ingest(MinecraftObservationEvent(
        "self_snapshot",
        {
            "username": "bot",
            "inventory": [],
            "nearby_blocks": [
                {"name": "oak_log",
                 "position": {"x": 3, "y": 64, "z": 2},
                 "distance": 3.2},
            ],
        }, sequence=1,
    ))
    data = state.compact()
    assert data["nearby_blocks"][0]["name"] == "oak_log"
    assert MinecraftStateProjection.from_compact(
        data, max_entities=4,
    ).compact() == data

    bad = [dict(data, nearby_blocks=[{
        "name": "diamond_ore", "position": {"x": 99, "y": 64, "z": 99},
        "distance": 500.0,
    }]), dict(data, nearby_blocks=[{"name": "log", "hidden_seed": 9}])]
    for value in bad:
        with pytest.raises(ValueError):
            MinecraftStateProjection.from_compact(value, max_entities=4)


def test_entity_state_is_frozen_and_projection_owns_typed_rows() -> None:
    state = _state_with_entity()
    entity = state.entities["entity-1"]

    assert isinstance(entity, MinecraftEntityState)
    assert entity.entity_id == "entity-1"
    assert entity.runtime_id == 42
    assert entity.username == "zed"
    assert entity.name == "zombie"
    with pytest.raises(FrozenInstanceError):
        entity.name = "mutated"  # type: ignore[misc]


def test_entity_compact_preserves_public_json_shape() -> None:
    state = _state_with_entity()

    assert state.compact()["nearby_entities"] == [
        {
            "id": "entity-1",
            "runtime_id": 42,
            "username": "zed",
            "name": "zombie",
            "mob_type": "zombie",
            "type": "mob",
            "position": {"x": 1.0, "y": 64.0, "z": -2.0},
            "distance": 3.5,
        }
    ]


def test_decision_view_is_columnar_actionable_and_omits_evidence_only_sequence() -> None:
    state = _state_with_entity()
    view = state.decision_view()

    assert "last_event_sequence" not in view
    entities = view["nearby_entities"]
    assert entities["mode"] == "summary"
    assert entities["columns"] == [
        "runtime_id",
        "username",
        "name",
        "mob_type",
        "type",
        "distance",
        "x",
        "y",
        "z",
    ]
    assert entities["rows"] == [
        [42, "zed", "zombie", "zombie", "mob", 3.5, 1.0, 64.0, -2.0]
    ]
    assert entities["counts"] == {"zombie": 1}
    assert state.compact()["nearby_entities"][0]["id"] == "entity-1"
    assert "entity-1" not in repr(entities["rows"])


def test_decision_view_can_hide_stale_entities_without_mutating_durable_state() -> None:
    state = _state_with_entity()
    durable_before = state.compact()

    view = state.decision_view(include_entities=False)

    assert "nearby_entities" not in view
    assert state.compact() == durable_before


def test_compact_round_trip_restores_typed_entity_and_digest() -> None:
    state = _state_with_entity()
    compact = state.compact()

    restored = MinecraftStateProjection.from_compact(compact, max_entities=4)

    assert isinstance(restored.entities["entity-1"], MinecraftEntityState)
    assert restored.compact() == compact
    assert restored.snapshot_digest() == state.snapshot_digest()


def test_live_projection_rejects_duplicate_entity_identity_before_swap() -> None:
    state = _state_with_entity()
    prior = state.compact()
    with pytest.raises(ValueError, match="duplicate identity"):
        state.ingest(MinecraftObservationEvent(
            "entity_snapshot",
            {"entities": [
                {"uuid": "duplicate", "id": 1},
                {"uuid": "duplicate", "id": 2},
            ]},
            sequence=2,
        ))
    # The entity generation swap is atomic. The malformed transport event still
    # consumes its stream sequence, but cannot leak a half-built entity table.
    assert state.compact()["nearby_entities"] == prior["nearby_entities"]
    assert state.last_event_sequence == 2


def test_live_projection_rejects_nonfinite_health_and_invalid_inventory_rows() -> None:
    state = MinecraftStateProjection(max_entities=4)
    with pytest.raises(ValueError, match="health must be finite"):
        state.ingest(MinecraftObservationEvent(
            "health", {"health": float("nan")}, sequence=1,
        ))

    with pytest.raises(ValueError, match="inventory observation row"):
        state.ingest(MinecraftObservationEvent(
            "self_snapshot",
            {"username": "bot", "inventory": [{"name": "oak_log", "count": True}]},
            sequence=2,
        ))


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
                "entity_snapshot",
                {"entities": [{"uuid": "bad-position", "position": {"x": 1, "y": 2}}]},
                sequence=1,
            )
        )
    with pytest.raises(ValueError, match="observation distance"):
        invalid.ingest(
            MinecraftObservationEvent(
                "entity_snapshot",
                {"entities": [{"uuid": "bad-distance", "distance": True}]},
                sequence=2,
            )
        )



def test_same_stream_sequence_cannot_apply_world_change_twice() -> None:
    """Sequence identity fences duplicate causal effects, including deaths."""
    state = MinecraftStateProjection()
    first = MinecraftObservationEvent(
        "death", {}, sequence=1, stream_id="stream-a",
    )
    state.ingest(first)
    assert state.deaths == 1
    with pytest.raises(ValueError, match="not strictly increasing"):
        state.ingest(first)
    assert state.deaths == 1
    with pytest.raises(ValueError, match="not strictly increasing"):
        state.ingest(MinecraftObservationEvent(
            "death", {"different": True}, sequence=1, stream_id="stream-a",
        ))
    assert state.deaths == 1
    # A recycled bridge starts a different sequence domain; world evidence
    # must survive its transport reset.
    state.ingest(MinecraftObservationEvent(
        "health", {"health": 17}, sequence=1, stream_id="stream-b",
    ))
    assert state.deaths == 1
    assert state.health == 17


def test_single_state_materialization_supplies_identical_snapshot_and_digest() -> None:
    from unittest.mock import patch
    from noetrium_platform.foundation.kernel.kernel import canonical_digest
    from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
        MinecraftEnvironmentSession,
    )
    state = _state_with_entity()
    with patch.object(MinecraftStateProjection, "compact", wraps=state.compact) as materialize:
        payload = MinecraftEnvironmentSession._state_payload(
            type("SessionProxy", (), {"_state": state})()
        )
    assert materialize.call_count == 1
    assert payload["state_digest"] == canonical_digest(payload["state"])
    assert payload["state"]["nearby_entities"][0]["id"] == "entity-1"



def test_projection_partial_batch_failure_fences_session_without_replay() -> None:
    from types import SimpleNamespace
    from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
        MinecraftEnvironmentFailure,
    )
    from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
        MinecraftEnvironmentSession,
    )

    state = MinecraftStateProjection()
    errors = []
    proxy = SimpleNamespace(
        _closed=False, _restore_faulted=False, _projection_faulted=False,
        _state=state,
        _failure_log=lambda *args, **kwargs: errors.append((args, kwargs)),
    )
    # World events cannot be atomically rolled back after a malformed later
    # event. Their session must no longer be trusted for future decisions.
    with pytest.raises(MinecraftEnvironmentFailure, match="state"):
        MinecraftEnvironmentSession._ingest_events(
            proxy,
            (
                MinecraftObservationEvent("death", {}, sequence=1, stream_id="e"),
                MinecraftObservationEvent("death", {}, sequence=1, stream_id="e"),
            ),
            phase="observe",
        )
    assert state.deaths == 1
    assert proxy._projection_faulted is True
    with pytest.raises(RuntimeError, match="state projection failure"):
        MinecraftEnvironmentSession._assert_open(proxy)
    assert errors[0][1]["code"] == "MINECRAFT_STATE_PROJECTION_FAILED"
