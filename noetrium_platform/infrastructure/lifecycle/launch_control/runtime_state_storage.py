from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .runtime_state_codec import RuntimeControlStateCodec
from .runtime_state_contracts import RuntimeControlState


class FileRuntimeControlStateStore:
    """Filesystem backend for the authoritative runtime-control state document."""

    def __init__(self, path: Path, codec: RuntimeControlStateCodec | None = None) -> None:
        self._path = path
        self._codec = codec or RuntimeControlStateCodec()

    def exists(self) -> bool:
        return self._path.exists()

    def write(self, state: RuntimeControlState) -> None:
        atomic_replace_bytes(self._path, self._codec.encode(state))

    def read(self) -> RuntimeControlState:
        return self._codec.decode(self._path.read_bytes())

    def reference(self) -> str:
        return str(self._path)


__all__ = ["FileRuntimeControlStateStore"]
