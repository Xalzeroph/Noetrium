from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat

from .heartbeat_codec import ServiceHeartbeatCodec


class FileServiceHeartbeatStore:
    """Filesystem backend for per-deployment service heartbeats."""

    def __init__(self, root: Path, codec: ServiceHeartbeatCodec | None = None) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._codec = codec or ServiceHeartbeatCodec()

    def _path(self, deployment_id: str) -> Path:
        return self._root / f"{deployment_id}.json"

    def exists(self, deployment_id: str) -> bool:
        return self._path(deployment_id).exists()

    def write(self, heartbeat: ServiceHeartbeat) -> None:
        atomic_replace_bytes(self._path(heartbeat.deployment_id), self._codec.encode(heartbeat))

    def read(self, deployment_id: str) -> ServiceHeartbeat:
        return self._codec.decode(self._path(deployment_id).read_bytes())

    def reference(self, deployment_id: str) -> str:
        return str(self._path(deployment_id))


__all__ = ["FileServiceHeartbeatStore"]
