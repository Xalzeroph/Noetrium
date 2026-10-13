from __future__ import annotations

import subprocess
from threading import Lock


class LinuxChildRegistry:
    """Own local ``Popen`` handles without creating a second wait authority."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def remember(self, child: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._children[child.pid] = child

    def get(self, pid: int) -> subprocess.Popen[bytes] | None:
        with self._lock:
            return self._children.get(pid)

    def poll(self, pid: int) -> int | None:
        child = self.get(pid)
        return child.poll() if child is not None else None

    def forget(self, pid: int) -> subprocess.Popen[bytes] | None:
        with self._lock:
            return self._children.pop(pid, None)


__all__ = ["LinuxChildRegistry"]
