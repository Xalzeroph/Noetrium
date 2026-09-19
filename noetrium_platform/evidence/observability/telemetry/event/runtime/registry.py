from __future__ import annotations

from ..api.contracts import EventDefinition


class EventRegistry:
    def __init__(self) -> None:
        self._defs: dict[str, EventDefinition] = {}
        self._emitters: dict[str, set[str]] = {}

    def register(self, definition: EventDefinition) -> None:
        if definition.name in self._defs and self._defs[definition.name] != definition:
            raise ValueError(f"event redefined: {definition.name}")
        self._defs[definition.name] = definition

    def bind_emitter(self, event_name: str, component_id: str) -> None:
        if event_name not in self._defs:
            raise KeyError(f"unknown event: {event_name}")
        self._emitters.setdefault(event_name, set()).add(component_id)

    def audit_emitters(self) -> tuple[str, ...]:
        return tuple(
            f"event has no emitter: {name}"
            for name in sorted(self._defs)
            if not self._emitters.get(name)
        )

    def validate_payload(self, event_name: str, payload: dict[str, object]) -> None:
        definition = self._defs[event_name]
        missing = [field for field in definition.required_fields if field not in payload]
        if missing:
            raise ValueError(f"{event_name} missing fields {missing}")


__all__ = ["EventRegistry"]
