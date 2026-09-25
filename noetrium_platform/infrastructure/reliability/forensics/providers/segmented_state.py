from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import ZERO_HASH


@dataclass(frozen=True, slots=True)
class SegmentWriterState:
    initialized: bool = False
    tail_hash: str = ZERO_HASH
    count: int = 0
    active_index: int = 0
    active_rows: int = 0
    active_start_prev: str = ZERO_HASH
    active_signature: tuple[int, int, int, int] | None = None
    directory_signature: tuple[int, int, int, int] | None = None


class SegmentStateCell:
    """Single in-memory authority for segmented ledger writer state."""

    def __init__(self) -> None:
        self._state = SegmentWriterState()

    @property
    def value(self) -> SegmentWriterState:
        return self._state

    def replace(self, state: SegmentWriterState) -> SegmentWriterState:
        self._state = state
        return state
