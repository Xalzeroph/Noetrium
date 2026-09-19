from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import cast

from noetrium_platform.foundation.kernel.kernel import JsonInput, freeze_json, thaw_json


def _project(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _project(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return _project(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("operator JSON mappings require native string keys")
            projected[key] = _project(item)
        return projected
    if type(value) in (list, tuple):
        return [_project(item) for item in value]
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise TypeError(f"unsupported operator JSON value: {type(value).__name__}")


def plain_json(value: object) -> object:
    """Project typed product values onto ROLE01 strict finite JSON."""

    projected = _project(value)
    frozen = freeze_json(cast(JsonInput, projected))
    return thaw_json(frozen)


def render_json(value: object) -> str:
    return json.dumps(
        plain_json(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )


__all__ = ["plain_json", "render_json"]
