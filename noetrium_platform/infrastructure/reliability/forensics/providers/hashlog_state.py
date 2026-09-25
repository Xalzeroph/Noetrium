from __future__ import annotations

from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import WriterTail


class HashTailStateCell:
    """Single in-memory authority for verified single-ledger tail state."""

    def __init__(self)->None:
        self._state=WriterTail()

    @property
    def value(self)->WriterTail:
        return self._state

    def verified(
        self,
        count:int,
        tail_hash:str,
        signature:tuple[int,int,int,int]|None,
    )->WriterTail:
        self._state=self._state.verified(count,tail_hash,signature)
        return self._state

    def appended(
        self,
        row_hash:str,
        signature:tuple[int,int,int,int]|None,
        *,
        synced:bool,
    )->WriterTail:
        self._state=self._state.appended(row_hash,signature,synced=synced)
        return self._state
