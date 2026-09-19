from __future__ import annotations

from pathlib import Path
from types import TracebackType

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
)


class ReleaseFreezeBusy(RuntimeError):
    pass


class ReleaseFreezeLock:
    """Exclusive worktree-level guard for release regression/evidence/package operations.

    The lock file deliberately lives *outside* the source root. Holding the lock therefore
    cannot mutate the source manifest being frozen. Kernel flock ownership is process-bound,
    so abrupt process exit releases the lock automatically even if the persistent guard file
    remains on disk.
    """

    def __init__(self, root: Path, *, blocking: bool = False) -> None:
        self.root = Path(root).resolve()
        self.path = self.root.parent / f".{self.root.name}.release-freeze.lock"
        self._lock = InterprocessFileLock(self.path, blocking=blocking)

    def __enter__(self) -> "ReleaseFreezeLock":
        try:
            self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise ReleaseFreezeBusy("another release freeze operation is already active") from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._lock.__exit__(exc_type, exc, tb)


__all__ = ["ReleaseFreezeBusy", "ReleaseFreezeLock"]
