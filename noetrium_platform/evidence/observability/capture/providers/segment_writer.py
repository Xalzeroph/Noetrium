from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock, fsync_directory

from ..api.contracts import RawObservationReceipt
from .segment_recovery import recover_raw_segment


@dataclass(frozen=True, slots=True)
class SegmentWriterState:
    sequence: int
    closed: bool
    faulted: bool = False


class RawSegmentWriter:
    """Single-process-owner, crash-durable append writer for one raw segment."""

    def __init__(self, target: Path, family: str, schema_version: str, run_id: str) -> None:
        self.target = target
        self.family = family
        self.schema_version = schema_version
        self.run_id = run_id
        target.parent.mkdir(parents=True, exist_ok=True)
        self._ownership_lock = InterprocessFileLock(
            target.with_name(target.name + ".writer.lock"),
            blocking=False,
        )
        self._ownership_lock.__enter__()
        try:
            recovered = recover_raw_segment(
                target,
                family=family,
                schema_version=schema_version,
                run_id=run_id,
            )
            self.idempotency = recovered.idempotency
            self._state = SegmentWriterState(recovered.sequence, False)
            flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
            if os.name == "nt":
                flags |= getattr(os, "O_BINARY", 0)
            self._flags = flags
            existed = target.exists()
            self._fd = None if os.name == "nt" else os.open(target, flags, 0o644)
            if self._fd is not None and not existed:
                fsync_directory(target.parent)
        except BaseException:
            self._ownership_lock.__exit__(None, None, None)
            raise

    @property
    def sequence(self) -> int:
        return self._state.sequence

    @staticmethod
    def _write_all(fd: int, encoded: bytes) -> None:
        view = memoryview(encoded)
        total = 0
        while total < len(view):
            written = os.write(fd, view[total:])
            if written <= 0:
                raise OSError("raw segment write returned zero bytes")
            total += written

    def previous(self, idempotency_key: str) -> RawObservationReceipt | None:
        return self.idempotency.get(idempotency_key)

    def append(self, encoded: bytes, receipt: RawObservationReceipt, idempotency_key: str | None) -> None:
        if self._state.closed:
            raise RuntimeError("raw segment writer is closed")
        if self._state.faulted:
            raise RuntimeError("raw segment writer is faulted; close and reopen to reconcile")
        created = not self.target.exists()
        fd = self._fd
        owned_fd = False
        if fd is None:
            fd = os.open(self.target, self._flags, 0o644)
            owned_fd = True
        try:
            self._write_all(fd, encoded)
            os.fsync(fd)
            if created:
                fsync_directory(self.target.parent)
        except BaseException:
            self._state = SegmentWriterState(self._state.sequence, False, True)
            raise
        finally:
            if owned_fd:
                os.close(fd)
        self._state = SegmentWriterState(receipt.sequence, False)
        if idempotency_key is not None:
            self.idempotency[idempotency_key] = receipt

    def close(self) -> None:
        if self._state.closed:
            return
        close_error: BaseException | None = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except BaseException as exc:
                close_error = exc
            self._fd = None
        try:
            self._ownership_lock.__exit__(None, None, None)
        except BaseException as exc:
            if close_error is None:
                close_error = exc
        self._state = SegmentWriterState(self._state.sequence, True, self._state.faulted)
        if close_error is not None:
            raise close_error
