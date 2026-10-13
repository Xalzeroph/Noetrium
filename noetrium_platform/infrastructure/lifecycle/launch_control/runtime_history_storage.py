from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_append import durable_append_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock


class FileRuntimeHistoryStorage:
    """Filesystem backend for opaque runtime-history rows with cross-process exclusion."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._guard_path = path.with_name(path.name + ".guard.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def lines(self) -> tuple[str, ...]:
        if not self._path.exists():
            return ()
        return tuple(self._path.read_text(encoding="utf-8").splitlines())

    def append(self, encoded_row: bytes) -> None:
        durable_append_bytes(self._path, encoded_row)

    def reference(self) -> str:
        return str(self._path)

    def exclusive(self) -> InterprocessFileLock:
        return InterprocessFileLock(self._guard_path)


__all__ = ["FileRuntimeHistoryStorage"]
