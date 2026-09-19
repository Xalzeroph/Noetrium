from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.process.api import CaptureRotationReceipt, CaptureSyncReceipt, CaptureWriterState
from .fd import CaptureFD
from .state import CaptureStateCell
from .storage import CaptureStorage
from .tail import BoundedTail


class ActiveCaptureWriter:
    """Actor-owned mutable state for one segmented process stream.

    Every method is intentionally lock-free.  The owning SegmentedByteCapture
    submits all mutations and durability operations to one SerialActor lane, so
    filesystem I/O is serialized by ownership rather than by holding a Python
    lock across os.write/fsync/close.
    """

    def __init__(
        self,
        storage: CaptureStorage,
        *,
        max_segment_bytes: int,
        fsync_every_bytes: int,
        tail_bytes: int,
    ) -> None:
        self.storage = storage
        self.max_segment_bytes = max_segment_bytes
        self.fsync_every_bytes = fsync_every_bytes
        self.tail_bytes = tail_bytes

        resume_state = storage.resume_state()
        self._state = CaptureStateCell(resume_state)
        self._tail = BoundedTail(tail_bytes, storage.load_tail_from_state(resume_state, tail_bytes))
        self._fd = CaptureFD(storage.path(resume_state.index))
        if not self._state.value.sealed:
            self._fd.open()

    @property
    def state(self) -> CaptureWriterState:
        return self._state.value

    def _rotate(self) -> CaptureRotationReceipt:
        old = self._state.value
        self._fd.close(sync=bool(old.since_sync))
        new = self._state.rotated()
        self._fd = CaptureFD(self.storage.path(new.index))
        self._fd.open()
        return CaptureRotationReceipt(old.index, new.index, new.total_bytes)

    def append(self, data: bytes) -> tuple[CaptureRotationReceipt, ...]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("capture accepts bytes")
        if not data:
            return ()
        if self._state.value.sealed:
            raise RuntimeError("capture already sealed")
        rotations = []
        view = memoryview(data)
        pos = 0
        while pos < len(view):
            if self._state.value.active_size >= self.max_segment_bytes:
                rotations.append(self._rotate())
            state = self._state.value
            n = min(len(view) - pos, self.max_segment_bytes - state.active_size)
            chunk = view[pos : pos + n]
            self._fd.write_all(chunk)
            self._tail.update(chunk)
            due = (state.since_sync + n) >= self.fsync_every_bytes
            if due:
                self._fd.sync()
            self._state.appended(n, synced=due)
            pos += n
        return tuple(rotations)

    def sync(self) -> CaptureSyncReceipt:
        state = self._state.value
        if state.sealed:
            raise RuntimeError("capture already sealed")
        self._fd.sync()
        synced = state.since_sync
        self._state.synced()
        self.storage.write_resume_state(self._state.value)
        return CaptureSyncReceipt(
            self.storage.stream,
            state.index,
            state.total_bytes,
            synced,
            self._tail.sha256(),
        )

    def flush_active(self) -> None:
        if not self._state.value.sealed:
            self._fd.sync()

    def tail(self, length: int | None = None) -> bytes:
        return self._tail.read(length)

    def close_for_seal(self) -> CaptureWriterState:
        self._fd.close(sync=True)
        self._state.synced()
        self.storage.write_resume_state(self._state.value)
        return self._state.value

    def mark_sealed(self, total_bytes: int) -> None:
        self._state.sealed(total_bytes)
        self.storage.write_resume_state(self._state.value)

    def close(self) -> None:
        state = self._state.value
        self._fd.close(sync=bool(state.since_sync))
        if not state.sealed:
            self._state.synced()
            self.storage.write_resume_state(self._state.value)
