from __future__ import annotations

from typing import Protocol, cast

from noetrium_platform.evidence.data._canonical import canonical_bytes, strict_json_loads
from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.kernel.durability import sha256_bytes


class StatePayloadCodec(Protocol):
    def encode(self, payload: JsonValue) -> bytes: ...
    def decode(self, raw: bytes) -> JsonValue: ...


class StrictJsonStatePayloadCodec:
    """Canonical durable-state codec for plain scientific JSON data."""

    def encode(self, payload: JsonValue) -> bytes:
        return canonical_bytes(payload)

    def decode(self, raw: bytes) -> JsonValue:
        return cast(JsonValue, strict_json_loads(raw))


payload_sha256 = sha256_bytes
