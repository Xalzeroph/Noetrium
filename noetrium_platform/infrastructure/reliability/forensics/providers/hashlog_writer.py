from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.durability import (
    AppendDurability,
    append_bytes,
)

import os
from pathlib import Path

from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import encode_row, stat_signature
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_state import HashTailStateCell


class HashLedgerWriter:
    """Owns append/fsync mechanics only; ownership verification lives in façade."""

    def __init__(
        self,
        path:Path,
        state:HashTailStateCell,
        *,
        fsync_every:int,
    )->None:
        self.path=path
        self.state=state
        self.fsync_every=fsync_every

    def append(self,payload:dict[str,object])->str:
        state=self.state.value
        encoded,row_hash=encode_row(state.tail_hash,payload)
        due=(state.since_sync+1)>=self.fsync_every
        append_bytes(
            self.path,
            encoded,
            durability=(
                AppendDurability.DURABLE
                if due
                else AppendDurability.BUFFERED
            ),
            buffering=1024 * 1024,
            sync_parent=due,
        )
        self.state.appended(row_hash,stat_signature(self.path),synced=due)
        return row_hash
