from __future__ import annotations


def require_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be stored as SQLite TEXT")
    return value


def require_optional_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return require_text(value, label=label)


def require_integer(value: object, *, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be stored as SQLite INTEGER")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


__all__ = ["require_integer", "require_optional_text", "require_text"]
