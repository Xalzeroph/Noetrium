from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SegmentedAppendReceipt:
    row_hash: str
    created_segment: bool

from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import encode_row, stat_signature
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_state import SegmentStateCell, SegmentWriterState


class SegmentedLedgerWriter:
    """Owns append/rotation mechanics; verification and manifest publication live elsewhere."""

    def __init__(
        self,
        root: Path,
        state: SegmentStateCell,
        *,
        max_segment_bytes: int,
        fsync_every: int,
    ) -> None:
        self.root = root
        self.state = state
        self.max_segment_bytes = max_segment_bytes
        self.fsync_every = fsync_every

    def path(self, index: int) -> Path:
        return self.root / f"{index:08d}.jsonl"

    def append(self, payload: dict[str, object]) -> SegmentedAppendReceipt:
        state = self.state.value
        encoded, row_hash = encode_row(state.tail_hash, payload)
        active = self.path(state.active_index)
        current_size = active.stat().st_size if active.exists() else 0
        index = state.active_index
        rows = state.active_rows
        start_prev = state.active_start_prev

        if rows > 0 and current_size + len(encoded) > self.max_segment_bytes:
            index += 1
            rows = 0
            start_prev = state.tail_hash
            active = self.path(index)

        due = (state.count + 1) % self.fsync_every == 0
        created_segment = not active.exists()
        mode = "xb" if created_segment else "ab"
        with active.open(mode, buffering=1024 * 1024) as handle:
            handle.write(encoded)
            handle.flush()
            if due:
                os.fsync(handle.fileno())

        self.state.replace(
            SegmentWriterState(
                initialized=True,
                tail_hash=row_hash,
                count=state.count + 1,
                active_index=index,
                active_rows=rows + 1,
                active_start_prev=start_prev,
                active_signature=stat_signature(active),
                directory_signature=stat_signature(self.root),
            )
        )
        return SegmentedAppendReceipt(row_hash=row_hash, created_segment=created_segment)
