from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, freeze_json

from .fidelity import MEMGPT_CLASSIC_FIDELITY


class MemGPTMemoryTier(StrEnum):
    CORE = "core"
    RECALL = "recall"
    ARCHIVAL = "archival"


@dataclass(frozen=True, slots=True)
class MemGPTMemoryQuery:
    tier: MemGPTMemoryTier
    query: str
    page: int = 0
    count: int = 5

    def __post_init__(self) -> None:
        if self.tier is MemGPTMemoryTier.CORE:
            raise ValueError("classic MemGPT core memory is edited in-context, not paged by query")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("MemGPT memory query is required")
        if type(self.page) is not int or self.page < 0:
            raise ValueError("MemGPT memory page must be non-negative")
        if type(self.count) is not int or self.count <= 0:
            raise ValueError("MemGPT memory page size must be positive")

    @property
    def start(self) -> int:
        # The audited 2023 paging fix changed `start=page` to `start=page*count`.
        return self.page * self.count


@dataclass(frozen=True, slots=True)
class MemGPTCoreMemory:
    """Method-owned editable blocks rendered into the model-visible context."""

    blocks: JsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.blocks, Mapping):
            raise TypeError("MemGPT core memory blocks must be a mapping")
        normalized: dict[str, JsonValue] = {}
        for label, value in self.blocks.items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError("MemGPT core-memory block labels must be non-empty")
            if not isinstance(value, str):
                raise TypeError("classic MemGPT core-memory block values must be text")
            normalized[label] = value
        object.__setattr__(self, "blocks", freeze_json(normalized))

    def replace(self, label: str, old: str, new: str) -> "MemGPTCoreMemory":
        current = self.blocks.get(label)
        if not isinstance(current, str):
            raise KeyError(label)
        if old not in current:
            raise ValueError("old core-memory content was not found")
        updated = dict(self.blocks)
        updated[label] = current.replace(old, new)
        return MemGPTCoreMemory(updated)

    def append(self, label: str, content: str) -> "MemGPTCoreMemory":
        current = self.blocks.get(label)
        if not isinstance(current, str):
            raise KeyError(label)
        updated = dict(self.blocks)
        updated[label] = current + "\n" + str(content)
        return MemGPTCoreMemory(updated)


@dataclass(frozen=True, slots=True)
class MemGPTSummaryPartition:
    """Exact model-view partition used by the audited paper-era overflow path.

    The underlying Noetrium Journal remains untouched. This describes only the
    historical MemGPT prompt transformation before retrying the same step.
    """

    summarize: tuple[JsonObject, ...]
    retain: tuple[JsonObject, ...]
    cutoff: int


def _message(row: Mapping[str, JsonValue]) -> JsonObject:
    return freeze_json(dict(row))


def classic_summary_partition(
    messages: Sequence[Mapping[str, JsonValue]],
    *,
    cutoff: int | None = None,
) -> MemGPTSummaryPartition:
    frozen = tuple(_message(row) for row in messages)
    if len(frozen) < 2:
        raise ValueError("MemGPT summarization requires system plus at least one message")
    if cutoff is None:
        cutoff = round((len(frozen) - 1) * MEMGPT_CLASSIC_FIDELITY.default_summary_fraction)
    if type(cutoff) is not int or not 1 <= cutoff < len(frozen):
        raise ValueError("MemGPT summary cutoff is outside the message history")
    # Match the 2023 source: if the selected cutoff message is a user message,
    # move the cutoff forward by one when possible. The system message at index
    # zero is never summarized.
    if frozen[cutoff].get("role") == "user" and cutoff + 1 < len(frozen):
        cutoff += 1
    return MemGPTSummaryPartition(
        summarize=frozen[1:cutoff],
        retain=frozen[cutoff:],
        cutoff=cutoff,
    )


__all__ = [
    "MemGPTCoreMemory",
    "MemGPTMemoryQuery",
    "MemGPTMemoryTier",
    "MemGPTSummaryPartition",
    "classic_summary_partition",
]
