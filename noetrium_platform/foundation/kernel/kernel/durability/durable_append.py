from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from .durable_file import flush_file_descriptor, fsync_directory


class DurableAppendError(RuntimeError):
    pass


class AppendDurability(StrEnum):
    BUFFERED = "buffered"
    DURABLE = "durable"


def append_bytes(
    path: Path,
    payload: bytes,
    *,
    durability: AppendDurability,
    buffering: int = -1,
    sync_parent: bool = False,
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

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    try:
        with path.open("ab", buffering=buffering) as handle:
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
    "append_bytes",
    "durable_append_bytes",
]
