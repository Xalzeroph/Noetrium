from __future__ import annotations


def normalize_authority_inputs(
    authority_inputs: tuple[tuple[str, str], ...],
    *,
    label: str = "research authority inputs",
) -> tuple[tuple[str, str], ...]:
    """Freeze explicit machine-local authority facts into canonical key order."""

    if type(authority_inputs) is not tuple:
        raise TypeError(f"{label} must be a tuple")
    normalized: list[tuple[str, str]] = []
    for row in authority_inputs:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError(f"{label} must contain text pairs")
        key, value = row
        if (
            type(key) is not str
            or not key.strip()
            or key != key.strip()
            or type(value) is not str
            or not value.strip()
            or value != value.strip()
        ):
            raise ValueError(f"{label} require canonical non-empty text")
        normalized.append((key, value))
    normalized.sort(key=lambda row: row[0])
    if len({key for key, _value in normalized}) != len(normalized):
        raise ValueError(f"{label} keys must be unique")
    return tuple(normalized)


def authority_input_value(
    authority_inputs: tuple[tuple[str, str], ...],
    key: str,
    *,
    label: str = "research authority input",
) -> str | None:
    """Resolve one exact authority fact without inference or fallback."""

    if type(key) is not str or not key.strip() or key != key.strip():
        raise ValueError(f"{label} key must be canonical text")
    for candidate, value in authority_inputs:
        if candidate == key:
            return value
    return None


__all__ = ["authority_input_value", "normalize_authority_inputs"]
