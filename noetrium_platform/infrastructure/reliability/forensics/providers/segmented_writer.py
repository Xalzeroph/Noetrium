from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability import (
    AppendDurability,
    append_bytes,
)
from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import (
    encode_row,
    stat_signature,
)
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_state import (
    SegmentStateCell,
    SegmentWriterState,
)


@dataclass(frozen=True, slots=True)
class SegmentedAppendReceipt:
    row_hash: str
    created_segment: bool


class SegmentedLedgerWriter:
    """Owns record/rotation policy while Platform owns append mechanics."""

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

    def append(
        self,
        payload: dict[str, object],
    ) -> SegmentedAppendReceipt:
        state = self.state.value
        encoded, row_hash = encode_row(state.tail_hash, payload)
        active = self.path(state.active_index)
        active_signature = state.active_signature
        if state.active_rows > 0 and active_signature is None:
            raise RuntimeError("active segmented ledger file lost its verified signature")
        current_size = 0 if active_signature is None else active_signature[2]
        index = state.active_index
        rows = state.active_rows
        start_prev = state.active_start_prev
        created_segment = active_signature is None

        if rows > 0 and current_size + len(encoded) > self.max_segment_bytes:
            index += 1
            rows = 0
            start_prev = state.tail_hash
            active = self.path(index)
            created_segment = True

        due = (state.count + 1) % self.fsync_every == 0
        append_bytes(
            active,
            encoded,
            durability=(
                AppendDurability.DURABLE
                if due
                else AppendDurability.BUFFERED
            ),
            buffering=1024 * 1024,
            exclusive_create=created_segment,
        )

        self.state.replace(
            SegmentWriterState(
                initialized=True,
                tail_hash=row_hash,
                count=state.count + 1,
                active_index=index,
                active_rows=rows + 1,
                active_start_prev=start_prev,
                active_signature=stat_signature(active),
                directory_signature=(
                    stat_signature(self.root)
                    if created_segment
                    else state.directory_signature
                ),
            )
        )
        return SegmentedAppendReceipt(
            row_hash=row_hash,
            created_segment=created_segment,
        )
