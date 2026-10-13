from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .fidelity import SEECLICK_FIDELITY

_POINT_PATTERN = re.compile(
    r"\(?\s*(?P<x>(?:0(?:\.\d+)?|1(?:\.0+)?))\s*,\s*"
    r"(?P<y>(?:0(?:\.\d+)?|1(?:\.0+)?))\s*\)?"
)


def _coordinate(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"SeeClick {field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not (
        SEECLICK_FIDELITY.coordinate_min
        <= number
        <= SEECLICK_FIDELITY.coordinate_max
    ):
        raise ValueError(f"SeeClick {field} must be within [0,1]")
    return number


@dataclass(frozen=True, slots=True)
class SeeClickPoint:
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _coordinate(self.x, "x"))
        object.__setattr__(self, "y", _coordinate(self.y, "y"))

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


def parse_seeclick_point(value: object) -> SeeClickPoint:
    if isinstance(value, Mapping):
        point = value.get("point", value)
        if isinstance(point, Mapping):
            return SeeClickPoint(
                _coordinate(point.get("x"), "x"),
                _coordinate(point.get("y"), "y"),
            )
        value = point
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows = tuple(value)
        if len(rows) != 2:
            raise ValueError("SeeClick point sequence must have length two")
        return SeeClickPoint(
            _coordinate(rows[0], "x"),
            _coordinate(rows[1], "y"),
        )
    if isinstance(value, str):
        match = _POINT_PATTERN.search(value)
        if match is None:
            raise ValueError("SeeClick point text does not contain normalized coordinates")
        return SeeClickPoint(float(match.group("x")), float(match.group("y")))
    raise TypeError("SeeClick point prediction must be object, sequence, or text")


def point_inside_bbox(
    point: SeeClickPoint,
    bbox: tuple[float, float, float, float],
) -> bool:
    if not isinstance(point, SeeClickPoint):
        raise TypeError("SeeClick grounding evaluation requires SeeClickPoint")
    if type(bbox) is not tuple or len(bbox) != 4:
        raise TypeError("SeeClick bbox must have four normalized coordinates")
    left, top, right, bottom = tuple(
        _coordinate(value, "bbox coordinate") for value in bbox
    )
    if not left < right or not top < bottom:
        raise ValueError("SeeClick bbox must have positive area")
    return left <= point.x <= right and top <= point.y <= bottom


__all__ = ["SeeClickPoint", "parse_seeclick_point", "point_inside_bbox"]
