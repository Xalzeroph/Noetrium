from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .service_state_codec import ServiceSupervisorStateCodec
from .service_state_contracts import ServiceSupervisorState


class FileServiceStateStore:
    """Filesystem backend for one authoritative service supervisor state document."""

    def __init__(self, path: Path, codec: ServiceSupervisorStateCodec | None = None) -> None:
        self._path = path
        self._codec = codec or ServiceSupervisorStateCodec()

    def exists(self) -> bool:
        return self._path.exists()

    def write(self, state: ServiceSupervisorState) -> None:
        atomic_replace_bytes(self._path, self._codec.encode(state))

    def read(self) -> ServiceSupervisorState:
        return self._codec.decode(self._path.read_bytes())

    def reference(self) -> str:
        return str(self._path)


__all__ = ["FileServiceStateStore"]
