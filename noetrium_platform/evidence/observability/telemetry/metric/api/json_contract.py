from __future__ import annotations

import json

from .errors import TelemetryMetricCorruptionError


def decode_string_map(raw: str, *, label: str) -> dict[str, str]:
    def reject_constant(token: str) -> object:
        raise TelemetryMetricCorruptionError(
            f"{label} contains non-finite JSON constant {token!r}"
        )

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise TelemetryMetricCorruptionError(
                    f"{label} contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    try:
        document = json.loads(
            raw,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except json.JSONDecodeError as exc:
        raise TelemetryMetricCorruptionError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in document.items()
    ):
        raise TelemetryMetricCorruptionError(
            f"{label} must be a string-to-string object"
        )
    return document


__all__ = ["decode_string_map"]
