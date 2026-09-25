from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from threading import RLock

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from ..api.state import ModelRunState


class FileModelSupervisorStateStore:
    """Atomic filesystem backend for the small model supervisor control record."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def write(self, state: ModelRunState) -> None:
        payload = canonical_bytes(state, indent=2)
        with self._lock:
            atomic_replace_bytes(self._path, payload)


__all__ = ["FileModelSupervisorStateStore"]
