from __future__ import annotations

import hashlib
import os
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fsync_dir(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class PromptPublicationError(RuntimeError):
    pass


class PromptPublicationLease:
    """One kernel-backed writer lease shared by staging and promotion transactions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock: InterprocessFileLock | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock = InterprocessFileLock(self.path, blocking=False)
            self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise PromptPublicationError("another prompt publication is active") from exc
        return self

    def __exit__(self, *exc):
        del exc
        lock = self._lock
        self._lock = None
        if lock is not None:
            lock.__exit__(None, None, None)
