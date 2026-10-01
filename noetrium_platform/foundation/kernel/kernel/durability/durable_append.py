from __future__ import annotations

from enum import StrEnum
import os
from pathlib import Path

from .durable_file import flush_file_descriptor, fsync_directory


class DurableAppendError(RuntimeError):
    pass


class AppendDurability(StrEnum):
    BUFFERED = "buffered"
    DURABLE = "durable"


class PersistentAppendFile:
    """Single canonical persistent append-file primitive.

    The kernel owns descriptor creation, append-only flags, partial-write
    handling, explicit durability barriers and descriptor close. Domain
    systems own record framing, rotation policy and when durability is required.
    """

    def __init__(self, path: str | Path, *, mode: int = 0o644) -> None:
        if type(mode) is not int or mode < 0:
            raise ValueError("append file mode must be a non-negative integer")
        self.path = Path(path)
        self.mode = mode
        self._fd: int | None = None

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self) -> None:
        if self._fd is not None:
            return
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if os.name == "nt":
            flags |= getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, self.mode)
        self._fd = fd
        if not existed:
            try:
                fsync_directory(parent)
            except BaseException:
                try:
                    os.close(fd)
                finally:
                    self._fd = None
                raise

    def write_all(self, payload: bytes | bytearray | memoryview) -> None:
        fd = self._fd
        if fd is None:
            raise RuntimeError("append file is not open")
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError("append write returned zero bytes")
            offset += written

    def sync(self) -> None:
        fd = self._fd
        if fd is None:
            raise RuntimeError("append file is not open")
        flush_file_descriptor(fd)

    def close(self, *, sync: bool = False) -> None:
        fd = self._fd
        if fd is None:
            return
        primary: BaseException | None = None
        try:
            if sync:
                flush_file_descriptor(fd)
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                os.close(fd)
            except BaseException as close_exc:
                if primary is None:
                    raise
                primary.add_note(
                    "append file close failed: "
                    f"{type(close_exc).__name__}"
                )
            finally:
                self._fd = None

    def __enter__(self) -> "PersistentAppendFile":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        self.close()
        return False


def append_bytes(
    path: Path,
    payload: bytes,
    *,
    durability: AppendDurability,
    buffering: int = -1,
    sync_parent: bool = False,
    exclusive_create: bool = False,
) -> None:
    """Append bytes through the single platform append implementation.

    BUFFERED flushes Python buffers to the OS only. DURABLE additionally
    fsyncs the file. Parent-directory sync is automatic on durable first-create
    and can be forced for batched durability checkpoints.
    """
    if not isinstance(durability, AppendDurability):
        raise TypeError("append durability must be AppendDurability")
    if type(buffering) is not int or buffering < -1:
        raise ValueError("append buffering must be -1 or a non-negative integer")
    if type(exclusive_create) is not bool:
        raise TypeError("exclusive_create must be bool")

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    try:
        mode = "xb" if exclusive_create else "ab"
        with path.open(mode, buffering=buffering) as handle:
            handle.write(payload)
            handle.flush()
            if durability is AppendDurability.DURABLE:
                flush_file_descriptor(handle.fileno())
        if durability is AppendDurability.DURABLE and (
            sync_parent or not existed
        ):
            fsync_directory(parent)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableAppendError(f"append failed for {path}") from exc


def write_all_file_descriptor(
    fd: int,
    payload: bytes | bytearray | memoryview,
) -> None:
    """Write a complete byte payload to an already-owned descriptor.

    Descriptor creation/close and semantic ownership remain with the caller.
    The kernel owns the partial-write loop so raw os.write never escapes the
    filesystem/process durability boundary.
    """
    if type(fd) is not int or fd < 0:
        raise ValueError("file descriptor must be a non-negative integer")
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("file-descriptor write made no progress")
        offset += written


def durable_append_bytes(path: Path, payload: bytes) -> None:
    """Append bytes and make the new complete prefix crash-durable."""
    append_bytes(
        path,
        payload,
        durability=AppendDurability.DURABLE,
    )


__all__ = [
    "AppendDurability",
    "DurableAppendError",
    "PersistentAppendFile",
    "append_bytes",
    "durable_append_bytes",
    "write_all_file_descriptor",
]
