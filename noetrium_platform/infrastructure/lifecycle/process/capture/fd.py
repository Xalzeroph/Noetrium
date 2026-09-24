from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability import PersistentAppendFile


class CaptureFD:
    """Process-capture adapter over the canonical platform append primitive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._append = PersistentAppendFile(path)

    def open(self) -> None:
        self._append.open()

    def write_all(self, view: memoryview) -> None:
        self._append.write_all(view)

    def sync(self) -> None:
        self._append.sync()

    def close(self, *, sync: bool) -> None:
        self._append.close(sync=sync)
