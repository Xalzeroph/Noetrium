from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, Protocol


class MinecraftActionContractError(ValueError):
    """A Minecraft action cannot satisfy the provider's typed input contract."""

    def __init__(self, action_type: str, code: str, message: str) -> None:
        super().__init__(
            f"Minecraft action contract failed [{code}] for {action_type}: {message}"
        )
        self.action_type = action_type
        self.code = code


class MinecraftActionCodec(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


def error(action_type: str, code: str, message: str) -> MinecraftActionContractError:
    return MinecraftActionContractError(action_type, code, message)


def number(action_type: str, name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise error(action_type, "FIELD_TYPE", f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise error(action_type, "FIELD_TYPE", f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise error(action_type, "FIELD_FINITE", f"{name} must be finite")
    return result


def integer(
    action_type: str,
    name: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int:
    numeric = number(action_type, name, value)
    result = int(numeric)
    if result != numeric or not minimum <= result <= maximum:
        raise error(
            action_type,
            "FIELD_RANGE",
            f"{name} must be an integer in [{minimum}, {maximum}]",
        )
    return result


def text(
    action_type: str,
    name: str,
    value: Any,
    *,
    maximum: int = 256,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(action_type, "FIELD_TEXT", f"{name} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise error(
            action_type,
            "FIELD_LENGTH",
            f"{name} must be at most {maximum} characters",
        )
    return result


def position(action_type: str, value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "z"}:
        raise error(
            action_type,
            "POSITION_SHAPE",
            "position must contain exactly x, y and z",
        )
    return {
        axis: number(action_type, f"position.{axis}", value[axis])
        for axis in ("x", "y", "z")
    }


def allowed(
    action_type: str,
    payload: Mapping[str, Any],
    names: set[str],
) -> dict[str, Any]:
    unknown = set(payload) - names
    if unknown:
        raise error(
            action_type,
            "UNKNOWN_FIELD",
            f"unexpected fields: {sorted(str(value) for value in unknown)}",
        )
    return dict(payload)


def distance(
    action_type: str,
    name: str,
    value: Any,
    *,
    default: float,
    minimum: float = 1.0,
    maximum: float = 128.0,
) -> float:
    result = number(action_type, name, default if value is None else value)
    if not minimum <= result <= maximum:
        raise error(
            action_type,
            "FIELD_RANGE",
            f"{name} must be in [{minimum}, {maximum}]",
        )
    return result


def item_count(
    action_type: str,
    value: Mapping[str, Any],
    *,
    maximum: int = 64,
) -> dict[str, Any]:
    return {
        "item": text(action_type, "item", value.get("item")),
        "count": integer(
            action_type,
            "count",
            value.get("count", 1),
            minimum=1,
            maximum=maximum,
        ),
    }


__all__ = [
    "MinecraftActionCodec",
    "MinecraftActionContractError",
    "allowed",
    "distance",
    "error",
    "integer",
    "item_count",
    "number",
    "position",
    "text",
]
