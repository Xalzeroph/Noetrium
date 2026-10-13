from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.lifecycle.process.api import (
    ByteSegment,
    CaptureIntegrityError,
    CaptureManifest,
    CaptureRotationReceipt,
    CaptureSyncReceipt,
    CaptureWriterState,
)
from .storage import CaptureStorage
from .writer import ActiveCaptureWriter


class SegmentedByteCapture:
    """Lossless process-stream capture owned by one serial actor.

    The caller must supply the process/task concurrency scope.  No hidden
    runtime or compatibility executor is created by this backend.
    """

    def __init__(
        self,
        root: Path,
        stream: str,
        *,
        task_group: TaskGroupPort,
        max_segment_bytes: int = 4 * 1024 * 1024,
        fsync_every_bytes: int = 1024 * 1024,
        tail_bytes: int = 256 * 1024,
    ) -> None:
        if max_segment_bytes <= 0 or fsync_every_bytes <= 0 or tail_bytes <= 0:
            raise ValueError("capture sizes must be positive")
        self.root = root
        self.stream = stream
        self.max_segment_bytes = max_segment_bytes
        self.fsync_every_bytes = fsync_every_bytes
        self.tail_bytes = tail_bytes
        self.storage = CaptureStorage(root, stream)
        self.manifest_path = self.storage.manifest_path
        actor_id = f"process-capture:{stream}:{root.resolve()}"
        self._actor = task_group.open_serial_actor(actor_id, lane_id=actor_id)
        self.writer = self._actor.call(
            "open-writer",
            ActiveCaptureWriter,
            self.storage,
            max_segment_bytes=max_segment_bytes,
            fsync_every_bytes=fsync_every_bytes,
            tail_bytes=tail_bytes,
        )

    def append(self, data: bytes) -> tuple[CaptureRotationReceipt, ...]:
        return self._actor.call("append", self.writer.append, data)

    def sync(self) -> CaptureSyncReceipt:
        return self._actor.call("sync", self.writer.sync)

    def manifest_reference(self) -> str:
        return str(self.manifest_path)

    def tail(self, length: int | None = None) -> bytes:
        return self._actor.call("tail", self.writer.tail, length)

    def _seal_owned(self) -> CaptureManifest:
        if self.writer.state.sealed:
            return self.storage.verify_manifest()
        self.writer.close_for_seal()
        manifest = self.storage.build_manifest(self.storage.scan_segments(), True)
        self.storage.write_manifest(manifest)
        self.writer.mark_sealed(manifest.total_bytes)
        return manifest

    def seal(self) -> CaptureManifest:
        return self._actor.call("seal", self._seal_owned)

    def _verify_owned(self) -> CaptureManifest:
        self.writer.flush_active()
        return self.storage.verify_manifest()

    def verify(self) -> CaptureManifest:
        return self._actor.call("verify", self._verify_owned)

    def read_range(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("offset/length must be non-negative")
        manifest = self.verify()
        end = min(offset + length, manifest.total_bytes)
        if offset >= end:
            return b""
        # verify() freezes the readable prefix through manifest.total_bytes.
        # Append-only writes after that point cannot mutate this prefix.
        return self.storage.read_range_unverified(offset, end - offset)

    def close(self) -> None:
        self._actor.call("close", self.writer.close)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = [
    "ByteSegment",
    "CaptureIntegrityError",
    "CaptureManifest",
    "CaptureWriterState",
    "CaptureRotationReceipt",
    "CaptureSyncReceipt",
    "SegmentedByteCapture",
]
