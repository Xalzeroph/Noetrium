from __future__ import annotations

import math
def mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    return value


def exact_fields(
    value: object,
    *,
    field: str,
    fields: frozenset[str],
) -> dict[str, object]:
    document = mapping(value, field=field)
    if frozenset(document) != fields:
        raise ValueError(f"{field} fields do not match the persisted schema")
    return document


def text(value: object, *, field: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return text(value, field=field)


def integer(value: object, *, field: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return value


def optional_integer(value: object, *, field: str, minimum: int | None = None) -> int | None:
    if value is None:
        return None
    return integer(value, field=field, minimum=minimum)


def number(value: object, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return result


def sequence(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    return value


def text_tuple(value: object, *, field: str) -> tuple[str, ...]:
    return tuple(
        text(item, field=f"{field}[{index}]")
        for index, item in enumerate(sequence(value, field=field))
    )


def text_pairs(value: object, *, field: str) -> tuple[tuple[str, str], ...]:
    rows = sequence(value, field=field)
    result: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError(f"{field}[{index}] must be a two-item JSON array")
        result.append((
            text(row[0], field=f"{field}[{index}][0]"),
            text(row[1], field=f"{field}[{index}][1]"),
        ))
    return tuple(result)
