from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from research.reproductions._support import JsonObject

VIMA_POLICY_AGENT_ID = "vima.policy"

def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed

def _float_tuple(value: object, *, length: int, field_name: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a numeric sequence")
    row = tuple(_finite(item, f"{field_name} component") for item in value)
    if len(row) != length:
        raise ValueError(f"{field_name} must contain exactly {length} values")
    return row

@dataclass(frozen=True, slots=True)
class VimaActionBounds:
    low: tuple[float, float]
    high: tuple[float, float]

    def __post_init__(self) -> None:
        low = _float_tuple(self.low, length=2, field_name="VIMA action bounds low")
        high = _float_tuple(self.high, length=2, field_name="VIMA action bounds high")
        if any(lower > upper for lower, upper in zip(low, high)):
            raise ValueError("VIMA action bounds must be ordered")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)

    def payload(self) -> JsonObject:
        return {"low": self.low, "high": self.high}

    @classmethod
    def from_payload(cls, value: object) -> "VimaActionBounds":
        if not isinstance(value, Mapping):
            raise TypeError("VIMA action bounds must be an object")
        return cls(
            low=_float_tuple(value.get("low"), length=2, field_name="VIMA action bounds low"),
            high=_float_tuple(value.get("high"), length=2, field_name="VIMA action bounds high"),
        )

__all__ = ("VIMA_POLICY_AGENT_ID", "VimaActionBounds")
