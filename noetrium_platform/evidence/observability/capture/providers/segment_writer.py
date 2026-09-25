from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    PersistentAppendFile,
)

from ..api.contracts import RawObservationReceipt
from .segment_recovery import recover_raw_segment


@dataclass(frozen=True, slots=True)
class SegmentWriterState:
    sequence: int
    closed: bool
    faulted: bool = False


class RawSegmentWriter:
    """Single-process-owner, crash-durable append writer for one raw segment."""

    def __init__(
        self,
        target: Path,
        family: str,
        schema_version: str,
        run_id: str,
    ) -> None:
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
            self._append = PersistentAppendFile(target)
        except BaseException:
            self._ownership_lock.__exit__(None, None, None)
            raise

    @property
    def sequence(self) -> int:
        return self._state.sequence

    def previous(
        self,
        idempotency_key: str,
    ) -> RawObservationReceipt | None:
        return self.idempotency.get(idempotency_key)

    def append(
        self,
        encoded: bytes,
        receipt: RawObservationReceipt,
        idempotency_key: str | None,
    ) -> None:
        if self._state.closed:
            raise RuntimeError("raw segment writer is closed")
        if self._state.faulted:
            raise RuntimeError(
                "raw segment writer is faulted; close and reopen to reconcile"
            )
        try:
            self._append.open()
            self._append.write_all(encoded)
            self._append.sync()
        except BaseException:
            self._state = SegmentWriterState(
                self._state.sequence,
                False,
                True,
            )
            raise
        self._state = SegmentWriterState(receipt.sequence, False)
        if idempotency_key is not None:
            self.idempotency[idempotency_key] = receipt

    def close(self) -> None:
        if self._state.closed:
            return
        close_error: BaseException | None = None
        try:
            self._append.close()
        except BaseException as exc:
            close_error = exc
        try:
            self._ownership_lock.__exit__(None, None, None)
        except BaseException as exc:
            if close_error is None:
                close_error = exc
        self._state = SegmentWriterState(
            self._state.sequence,
            True,
            self._state.faulted,
        )
        if close_error is not None:
            raise close_error
