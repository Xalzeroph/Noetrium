from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable, Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_bytes, canonical_digest

AGENT_ACTION_HISTORY_VIEW_SCHEMA = "agent-action-history-view.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical_object(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("agent history records must be mappings")
    decoded = json.loads(canonical_bytes(value))
    if not isinstance(decoded, dict):
        raise TypeError("agent history records must encode as JSON objects")
    return decoded


def _digest(records: tuple[Mapping[str, JsonValue], ...]) -> str:
    return canonical_digest(records)


@dataclass(frozen=True, slots=True)
class AgentActionHistoryProjectionReceipt:
    """Evidence that a model view was projected from complete durable action history."""

    schema_version: str
    source_count: int
    included_count: int
    omitted_count: int
    first_included_index: int | None
    source_digest: str
    included_digest: str
    omitted_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_ACTION_HISTORY_VIEW_SCHEMA:
            raise ValueError("unsupported agent action history projection schema")
        for name, value in (
            ("source_count", self.source_count),
            ("included_count", self.included_count),
            ("omitted_count", self.omitted_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.included_count + self.omitted_count != self.source_count:
            raise ValueError("agent history projection counts do not close")
        expected_first = self.omitted_count if self.included_count else None
        if self.first_included_index != expected_first:
            raise ValueError("agent history projection first index is inconsistent")
        for name, value in (
            ("source_digest", self.source_digest),
            ("included_digest", self.included_digest),
            ("omitted_digest", self.omitted_digest),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    @property
    def compacted(self) -> bool:
        return self.omitted_count > 0


@dataclass(frozen=True, slots=True)
class AgentActionHistoryProjection:
    """Model-facing history text plus a receipt back to the complete host history."""

    text: str
    receipt: AgentActionHistoryProjectionReceipt


def _render_history_envelope(
    included: tuple[Mapping[str, JsonValue], ...],
    *,
    source_count: int,
    omitted_count: int,
    source_digest: str,
    included_digest: str,
    omitted_digest: str,
) -> str:
    return json.dumps(
        {
            "schema": AGENT_ACTION_HISTORY_VIEW_SCHEMA,
            "source_count": source_count,
            "included_count": len(included),
            "omitted_count": omitted_count,
            "source_digest": source_digest,
            "included_digest": included_digest,
            "omitted_digest": omitted_digest,
            "actions": included,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def project_action_history(
    records: Iterable[Mapping[str, JsonValue]],
    *,
    max_chars: int,
) -> AgentActionHistoryProjection:
    """Project a maximal recent suffix without slicing any action record.

    Durable host history is never mutated. The projection chooses only complete
    records, emits omission evidence, and is deterministic for a fixed input and
    budget. ``max_chars`` is a participant-side pre-projection envelope; final
    model token admission remains owned by ``model/request``.
    """

    if type(max_chars) is not int or max_chars < 0:
        raise ValueError("agent history projection max_chars must be non-negative")
    source = tuple(_canonical_object(record) for record in records)
    source_digest = _digest(source)
    source_count = len(source)
    placeholder = "0" * 64

    def candidate_length(included_count: int) -> int:
        start = source_count - included_count
        return len(
            _render_history_envelope(
                source[start:],
                source_count=source_count,
                omitted_count=start,
                source_digest=placeholder,
                included_digest=placeholder,
                omitted_digest=placeholder,
            )
        )

    low, high = 0, source_count
    while low < high:
        middle = (low + high + 1) // 2
        if candidate_length(middle) <= max_chars:
            low = middle
        else:
            high = middle - 1
    included_count = low
    first_index = source_count - included_count
    included = source[first_index:]
    omitted = source[:first_index]
    included_digest = _digest(included)
    omitted_digest = _digest(omitted)
    receipt = AgentActionHistoryProjectionReceipt(
        schema_version=AGENT_ACTION_HISTORY_VIEW_SCHEMA,
        source_count=source_count,
        included_count=included_count,
        omitted_count=len(omitted),
        first_included_index=first_index if included else None,
        source_digest=source_digest,
        included_digest=included_digest,
        omitted_digest=omitted_digest,
    )
    text = _render_history_envelope(
        included,
        source_count=source_count,
        omitted_count=len(omitted),
        source_digest=source_digest,
        included_digest=included_digest,
        omitted_digest=omitted_digest,
    )
    if len(text) > max_chars:
        # Even the empty-history receipt may not fit. The host still receives a
        # complete receipt, while the model receives no malformed partial JSON.
        text = ""
    return AgentActionHistoryProjection(text=text, receipt=receipt)


__all__ = [
    "AGENT_ACTION_HISTORY_VIEW_SCHEMA",
    "AgentActionHistoryProjection",
    "AgentActionHistoryProjectionReceipt",
    "project_action_history",
]
