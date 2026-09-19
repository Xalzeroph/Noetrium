from __future__ import annotations

import os
from pathlib import Path

from .durable_file import fsync_directory


class DurableAppendError(RuntimeError):
    pass


def durable_append_bytes(path: Path, payload: bytes) -> None:
    """Append bytes and fsync the file; fsync the parent when the file is created.

    Ordering/concurrency semantics intentionally remain the caller's
    responsibility.  This primitive only provides filesystem durability.
    """

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    try:
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not existed:
            fsync_directory(parent)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableAppendError(f"durable append failed for {path}") from exc


__all__ = ["DurableAppendError", "durable_append_bytes"]
