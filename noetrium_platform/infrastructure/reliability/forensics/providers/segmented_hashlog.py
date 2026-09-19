from __future__ import annotations

from pathlib import Path
from threading import RLock

from noetrium_platform.infrastructure.reliability.forensics.api import VerifiedLedgerCut, VerifiedLedgerSlice
from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import stat_signature
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog import HashChainError
from noetrium_platform.infrastructure.reliability.forensics.providers.directory_change_signal import DirectoryChangeSignal
from noetrium_platform.infrastructure.reliability.forensics.providers.segment_verifier import (
    iter_segment_chain_payload_batches,
    scan_segment_chain,
    scan_segment_chain_cut,
    scan_segment_chain_payloads,
    segment_files,
)
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_manifest import SegmentManifestStore, SegmentSummary
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_state import SegmentStateCell, SegmentWriterState
from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_writer import SegmentedLedgerWriter


_OWNED_SEGMENT_NOTIFICATION_WAIT_SECONDS = 0.25


class SegmentedHashChainedJSONL:
    """Global hash chain façade over verifier, state cell, writer and manifest store."""

    def __init__(
        self,
        root:Path,
        *,
        max_segment_bytes:int=8*1024*1024,
        fsync_every:int=32,
        read_only:bool=False,
    )->None:
        if max_segment_bytes<=0:
            raise ValueError("max_segment_bytes must be positive")
        if fsync_every<=0:
            raise ValueError("fsync_every must be positive")
        self.root=root
        self.read_only=read_only
        if read_only:
            if not root.exists():
                raise FileNotFoundError(root)
        else:
            root.mkdir(parents=True,exist_ok=True)
        self.max_segment_bytes=max_segment_bytes
        self.fsync_every=fsync_every
        self.manifest_path=root/"manifest.json"
        self._lock=RLock()
        self._state=SegmentStateCell()
        self._writer=SegmentedLedgerWriter(
            root,self._state,
            max_segment_bytes=max_segment_bytes,
            fsync_every=fsync_every,
        )
        self._manifest=SegmentManifestStore(self.manifest_path)
        self._directory_signal=DirectoryChangeSignal(root)

    def _path(self,index:int)->Path:
        return self._writer.path(index)

    def _segment_files(self)->tuple[Path,...]:
        return segment_files(self.root)

    def _adopt_scan(self, result, *, publish_manifest: bool = False) -> tuple[int, str]:
        summaries=tuple(
            SegmentSummary(
                x.index,x.rows,x.bytes,x.start_prev_hash,x.end_hash,x.filename
            )
            for x in result.summaries
        )
        files=self._segment_files()
        idx=len(files)-1 if files else 0
        active=self._path(idx)
        self._state.replace(SegmentWriterState(
            initialized=True,
            tail_hash=result.tail_hash,
            count=result.total_rows,
            active_index=idx,
            active_rows=summaries[-1].rows if summaries else 0,
            active_start_prev=summaries[-1].start_prev_hash if summaries else result.tail_hash,
            active_signature=stat_signature(active),
            directory_signature=stat_signature(self.root),
        ))
        if publish_manifest:
            if self.read_only:
                raise PermissionError("read-only segmented ledger cannot publish manifest")
            self._manifest.write(summaries)
            state=self._state.value
            self._state.replace(SegmentWriterState(
                initialized=state.initialized,
                tail_hash=state.tail_hash,
                count=state.count,
                active_index=state.active_index,
                active_rows=state.active_rows,
                active_start_prev=state.active_start_prev,
                active_signature=state.active_signature,
                directory_signature=stat_signature(self.root),
            ))
        self._directory_signal.acknowledge()
        return result.total_rows,result.tail_hash

    def verify(self,*,publish_manifest:bool=False)->tuple[int,str]:
        with self._lock:
            return self._adopt_scan(
                scan_segment_chain(self.root), publish_manifest=publish_manifest
            )

    def verified_payloads_after(self, row_count: int) -> VerifiedLedgerSlice:
        """Return a verified append-only slice across all event segments."""
        with self._lock:
            result, verified = scan_segment_chain_payloads(
                self.root, start_after=row_count
            )
            total, tail = self._adopt_scan(result)
            if total != verified.total_rows or tail != verified.tail_hash:
                raise HashChainError("verified segment cut disagrees with adopted scan")
            return verified

    def verified_cut_after(self, row_count: int) -> VerifiedLedgerCut:
        """Verify one segmented cut without retaining its suffix payloads."""
        with self._lock:
            result, cut = scan_segment_chain_cut(self.root, start_after=row_count)
            total, tail = self._adopt_scan(result)
            if total != cut.total_rows or tail != cut.tail_hash:
                raise HashChainError("verified segment cut disagrees with adopted scan")
            return cut

    def iter_verified_payload_batches(
        self, cut: VerifiedLedgerCut, *, batch_size: int = 512
    ):
        """Re-verify one fixed segmented cut while yielding bounded batches."""
        with self._lock:
            yield from iter_segment_chain_payload_batches(
                self.root, cut=cut, batch_size=batch_size
            )

    def _ensure_owned(self)->None:
        state=self._state.value
        if not state.initialized:
            self.verify()
            return
        if (
            self._directory_signal.changed_since(state.directory_signature)
            or stat_signature(self._path(state.active_index))!=state.active_signature
        ):
            self.verify()
            raise HashChainError("segmented ledger changed outside owning writer")

    def _assert_owned_directory_namespace(self) -> None:
        state = self._state.value
        expected = {f"{index:08d}.jsonl" for index in range(state.active_index + 1)}
        if self.manifest_path.exists():
            expected.add(self.manifest_path.name)
        actual = {entry.name for entry in self.root.iterdir()}
        if actual != expected:
            extras = sorted(actual - expected)
            missing = sorted(expected - actual)
            raise HashChainError(
                f"segmented ledger directory namespace drift extras={extras} missing={missing}"
            )

    def append(self,payload:dict[str,object])->str:
        if self.read_only:
            raise PermissionError("read-only segmented ledger cannot append")
        with self._lock:
            self._ensure_owned()
            before=self._state.value
            receipt=self._writer.append(payload)
            changed=self._directory_signal.changed_since(before.directory_signature)
            if receipt.created_segment:
                if not changed:
                    changed = self._directory_signal.wait_changed_since(
                        before.directory_signature,
                        timeout_seconds=_OWNED_SEGMENT_NOTIFICATION_WAIT_SECONDS,
                    )
                if not changed:
                    raise HashChainError("owned segment creation was not observed by directory authority")
                self._assert_owned_directory_namespace()
                self._directory_signal.acknowledge()
            elif changed:
                raise HashChainError("segmented ledger directory changed during owning writer append")
            row_hash=receipt.row_hash
            state=self._state.value
            current_directory_signature=stat_signature(self.root)
            if current_directory_signature!=state.directory_signature:
                self._state.replace(SegmentWriterState(
                    initialized=state.initialized,
                    tail_hash=state.tail_hash,
                    count=state.count,
                    active_index=state.active_index,
                    active_rows=state.active_rows,
                    active_start_prev=state.active_start_prev,
                    active_signature=state.active_signature,
                    directory_signature=current_directory_signature,
                ))
            return row_hash

    def close(self)->None:
        with self._lock:
            self._directory_signal.close()

    def __enter__(self)->"SegmentedHashChainedJSONL":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback)->None:
        self.close()

    @property
    def cached_tail(self)->tuple[int,str]:
        with self._lock:
            state=self._state.value
            if not state.initialized:
                return self.verify()
            return state.count,state.tail_hash


__all__=["SegmentSummary","SegmentedHashChainedJSONL"]
