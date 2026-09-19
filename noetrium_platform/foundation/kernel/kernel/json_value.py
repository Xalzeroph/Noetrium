"""Shared JSON boundary types.

The platform uses JSON at a number of transport and artifact seams.  Keeping
the recursive types in the kernel prevents each subsystem from inventing an
``object`` payload contract while avoiding imports between environment and
experiment APIs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
JsonInput: TypeAlias = (
    JsonScalar | list["JsonInput"] | tuple["JsonInput", ...] | Mapping[str, "JsonInput"]
)
JsonObject: TypeAlias = Mapping[str, JsonValue]
JsonDocument: TypeAlias = Mapping[str, JsonInput]
JsonMutableValue: TypeAlias = JsonScalar | list["JsonMutableValue"] | dict[str, "JsonMutableValue"]


__all__ = [
    "JsonDocument",
    "JsonInput",
    "JsonMutableValue",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
]
