from __future__ import annotations

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
        with self.path.open("ab",buffering=1024*1024) as fh:
            fh.write(encoded)
            fh.flush()
            if due:
                os.fsync(fh.fileno())
        self.state.appended(row_hash,stat_signature(self.path),synced=due)
        return row_hash
