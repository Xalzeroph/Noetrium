from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
    InterprocessLockUnavailable,
)


class PublicationLock(InterprocessFileLock):
    """Nonblocking artifact adapter over the kernel lock authority."""

    def __init__(self, path: object) -> None:
        super().__init__(path, blocking=False)

PublicationLockBusy = InterprocessLockBusy
PublicationLockUnavailable = InterprocessLockUnavailable


__all__ = [
    "PublicationLock",
    "PublicationLockBusy",
    "PublicationLockUnavailable",
    "fsync_directory",
]
