from __future__ import annotations

from ..api import MinecraftJsonValue, MinecraftObservationEvent


def minecraft_events_payload(
    events: tuple[MinecraftObservationEvent, ...],
) -> list[dict[str, MinecraftJsonValue]]:
    """Render grounded bridge events into the stable observation JSON view."""

    return [
        {
            "kind": event.kind,
            "payload": dict(event.payload),
            "sequence": event.sequence,
            "timestamp_ms": event.timestamp_ms,
            "source": event.source,
            "request_id": event.request_id,
        }
        for event in events
    ]


__all__ = ["minecraft_events_payload"]
