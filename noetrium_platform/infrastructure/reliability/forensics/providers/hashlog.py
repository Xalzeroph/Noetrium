from __future__ import annotations

from pathlib import Path
from threading import RLock

from noetrium_platform.infrastructure.reliability.forensics.api import VerifiedLedgerCut, VerifiedLedgerSlice
from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import hash_payload, stat_signature
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_lookup import find_payload_in_hashlog
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_scanner import (
    HashChainError,
    iter_hash_chain_payload_batches,
    scan_hash_chain,
    scan_hash_chain_cut,
    scan_hash_chain_payloads,
)
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_state import HashTailStateCell
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_writer import HashLedgerWriter


class HashChainedJSONL:
    """Tamper-evident ledger façade over scanner, tail state, writer and lookup."""

    _hash=staticmethod(hash_payload)

    def __init__(
        self,
        path:Path,
        *,
        fsync_every:int=1,
        read_only:bool=False,
    ):
        if fsync_every<=0:
            raise ValueError("fsync_every must be positive")
        self.path=path
        self.read_only=read_only
        if read_only:
            if not path.parent.exists():
                raise FileNotFoundError(path.parent)
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=RLock()
        self._state=HashTailStateCell()
        self._writer=HashLedgerWriter(path,self._state,fsync_every=fsync_every)

    def verify(self)->tuple[int,str]:
        with self._lock:
            count,tail=scan_hash_chain(self.path)
            self._state.verified(count,tail,stat_signature(self.path))
            return count,tail

    def _ensure_owned_tail(self)->None:
        state=self._state.value
        if not state.initialized:
            self.verify()
            return
        if stat_signature(self.path)!=state.signature:
            scan_hash_chain(self.path)
            raise HashChainError(
                "ledger changed outside the owning writer; "
                "competing writer or external mutation detected"
            )

    def append(self,payload:dict[str,object])->str:
        if self.read_only:
            raise PermissionError("read-only hash ledger cannot append")
        with self._lock:
            self._ensure_owned_tail()
            return self._writer.append(payload)


    def verified_payloads_after(self, row_count: int) -> VerifiedLedgerSlice:
        """Return a verified append-only slice for disposable projection sync."""
        with self._lock:
            verified = scan_hash_chain_payloads(self.path, start_after=row_count)
            self._state.verified(
                verified.total_rows, verified.tail_hash, stat_signature(self.path)
            )
            return verified

    def verified_cut_after(self, row_count: int) -> VerifiedLedgerCut:
        """Verify an authoritative cut without materializing its suffix."""
        with self._lock:
            cut = scan_hash_chain_cut(self.path, start_after=row_count)
            self._state.verified(cut.total_rows, cut.tail_hash, stat_signature(self.path))
            return cut

    def iter_verified_payload_batches(
        self, cut: VerifiedLedgerCut, *, batch_size: int = 512
    ):
        """Re-verify one fixed cut while yielding only bounded payload batches."""
        with self._lock:
            yield from iter_hash_chain_payload_batches(
                self.path, cut=cut, batch_size=batch_size
            )

    def find_payload(
        self,
        field:str,
        value:object,
    )->dict[str,object]|None:
        """Verify authoritative chain before low-volume recovery lookup."""
        with self._lock:
            self.verify()
            return find_payload_in_hashlog(self.path,field,value)

    @property
    def cached_tail(self)->tuple[int,str]:
        with self._lock:
            state=self._state.value
            if not state.initialized:
                return self.verify()
            return state.count,state.tail_hash


__all__=["HashChainedJSONL","HashChainError"]
