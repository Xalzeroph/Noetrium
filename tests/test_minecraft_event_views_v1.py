from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftObservationEvent
from noetrium_platform.capabilities.environment.minecraft.runtime.event_views import minecraft_events_payload


def test_event_view_preserves_stable_json_shape_and_order() -> None:
    events = (
        MinecraftObservationEvent(
            "health",
            {"health": 20.0, "food": 18.0},
            sequence=4,
            timestamp_ms=123,
            source="mineflayer",
            request_id="request-1",
        ),
    )

    assert minecraft_events_payload(events) == [
        {
            "kind": "health",
            "payload": {"health": 20.0, "food": 18.0},
            "sequence": 4,
            "timestamp_ms": 123,
            "source": "mineflayer",
            "request_id": "request-1",
        }
    ]


def test_event_view_owns_top_level_payload_copy() -> None:
    event = MinecraftObservationEvent(
        "action_result",
        {"action_id": "a-1", "verified": True},
        sequence=1,
    )

    rendered = minecraft_events_payload((event,))
    rendered[0]["payload"]["verified"] = False

    assert event.payload["verified"] is True
