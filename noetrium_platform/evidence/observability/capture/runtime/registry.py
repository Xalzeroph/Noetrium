from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import JsonObject

from ..api.contracts import RawObservationSchema, RetentionClass


class RawObservationRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, RawObservationSchema] = {}

    def register(self, schema: RawObservationSchema) -> None:
        previous=self._schemas.get(schema.family)
        if previous is not None and previous != schema:
            raise ValueError(f"raw observation family redefined: {schema.family}")
        self._schemas[schema.family]=schema

    def schema(self, family: str) -> RawObservationSchema:
        try:
            return self._schemas[family]
        except KeyError as exc:
            raise KeyError(f"unregistered raw observation family: {family}") from exc

    def validate(self, family: str, payload: JsonObject) -> RawObservationSchema:
        schema=self.schema(family)
        missing=[field for field in schema.required_fields if field not in payload]
        if missing:
            raise ValueError(f"raw observation {family} missing required fields: {missing}")
        return schema

    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))


__all__ = ["RawObservationRegistry"]
