from __future__ import annotations

import hashlib
import json

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from .runtime_history_codec import (
    runtime_history_entry_from_document,
    runtime_state_digest,
    runtime_state_from_json,
)
from .runtime_history_contracts import (
    RUNTIME_HISTORY_ROW_SCHEMA_VERSION,
    RuntimeHistoryEntry,
    RuntimeHistoryProjectionKind,
)


_VALID_PROJECTION_KINDS = frozenset(item.value for item in RuntimeHistoryProjectionKind)


def verify_runtime_history_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    previous: str | None = None
    expected_sequence = 1
    for line_number, line in enumerate(lines, 1):
        try:
            stored = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid json")
            expected_sequence += 1
            continue
        if not isinstance(stored, dict):
            errors.append(f"line {line_number}: row must be object")
            expected_sequence += 1
            continue

        row = dict(stored)
        digest = row.pop("row_sha256", None)
        if row.get("sequence") != expected_sequence:
            errors.append(f"line {line_number}: sequence mismatch")
        if row.get("previous_sha256") != previous:
            errors.append(f"line {line_number}: chain mismatch")
        if row.get("schema_version") != RUNTIME_HISTORY_ROW_SCHEMA_VERSION:
            errors.append(f"line {line_number}: unsupported history row schema")

        state = row.get("state")
        if not isinstance(state, dict):
            errors.append(f"line {line_number}: state must be object")
        else:
            try:
                typed_state = runtime_state_from_json(state)
            except ValueError:
                errors.append(f"line {line_number}: state contract mismatch")
            else:
                if row.get("state_sha256") != runtime_state_digest(typed_state):
                    errors.append(f"line {line_number}: state digest mismatch")
        if row.get("projection_kind") not in _VALID_PROJECTION_KINDS:
            errors.append(f"line {line_number}: invalid projection kind")

        actual = hashlib.sha256(canonical_bytes(row)).hexdigest()
        if digest != actual:
            errors.append(f"line {line_number}: digest mismatch")
        previous = None if digest is None else str(digest)
        expected_sequence += 1
    return tuple(errors)


def runtime_history_tail(lines: tuple[str, ...]) -> RuntimeHistoryEntry | None:
    if not lines:
        return None
    try:
        document = json.loads(lines[-1])
        return runtime_history_entry_from_document(document)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("runtime history tail violates typed projection contract") from exc


__all__ = ["runtime_history_tail", "verify_runtime_history_lines"]
